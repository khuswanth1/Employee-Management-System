"""Tenant database lifecycle: provisioning, migration, engine cache.

Security notes:
- Tenant DB URLs are Fernet-encrypted in the platform DB and only decrypted here.
- In postgres mode each tenant gets its own role + database; the role owns only that database.
- Database/role names are generated server-side (hex), never derived from user input.
"""
import logging
import secrets
import threading
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.security import decrypt, encrypt
from app.db.platform_models import Company

log = logging.getLogger("worksphere.tenancy")
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _alembic_cfg(kind: str, engine: Engine | None = None, url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / f"alembic_{kind}"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    if engine is not None:
        cfg.attributes["engine"] = engine
    return cfg


def migrate_platform(engine: Engine) -> None:
    command.upgrade(_alembic_cfg("platform", engine=engine), "head")


def migrate_tenant(engine: Engine) -> None:
    command.upgrade(_alembic_cfg("tenant", engine=engine), "head")


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite ignores FKs unless enabled per connection
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return eng
    return create_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)


class TenantManager:
    def __init__(self) -> None:
        self._engines: dict[int, Engine] = {}
        self._sessions: dict[int, sessionmaker] = {}
        self._lock = threading.Lock()

    def engine_for(self, company: Company) -> Engine:
        eng = self._engines.get(company.id)
        if eng is None:
            with self._lock:
                eng = self._engines.get(company.id)
                if eng is None:
                    try:
                        url = decrypt(company.db_url_encrypted)
                    except Exception:
                        s = get_settings()
                        # only a developer machine may guess a local file; anywhere else a wrong key must stop the tenant
                        if s.environment == "development" and s.tenant_db_mode == "sqlite":
                            d = Path(s.tenant_sqlite_dir)
                            target = (d / f"{company.db_name}.db").resolve()
                            if target.exists():
                                url = f"sqlite:///{target.as_posix()}"
                                company.db_url_encrypted = encrypt(url)
                                log.warning(
                                    "Tenant '%s' DB URL could not be decrypted with current ENCRYPTION_KEY; "
                                    "auto-recovered SQLite URL to '%s'",
                                    company.slug, url,
                                )
                            else:
                                raise
                        else:
                            raise
                    eng = _make_engine(url)
                    self._engines[company.id] = eng
                    self._sessions[company.id] = sessionmaker(eng, expire_on_commit=False)
        return eng

    def session_for(self, company: Company) -> Session:
        self.engine_for(company)
        return self._sessions[company.id]()

    def forget(self, company_id: int) -> None:
        with self._lock:
            eng = self._engines.pop(company_id, None)
            self._sessions.pop(company_id, None)
        if eng is not None:
            eng.dispose()

    def dispose_all(self) -> None:
        for cid in list(self._engines):
            self.forget(cid)

    # ---- provisioning -------------------------------------------------------------------

    def provision(self, slug: str | None = None) -> tuple[str, str]:
        """Create a new empty tenant database and migrate it. Returns (db_name, encrypted_url).
        
        When `slug` is provided (e.g. 'company1'), the sub-database and SQLite file are
        formatted using the company slug (e.g. 'company1.db' in SQLite, 'company1' in Postgres).
        """
        import re
        s = get_settings()
        if slug:
            clean = re.sub(r"[^a-z0-9_]", "_", slug.lower().strip())
            db_name = clean
            if s.tenant_db_mode == "sqlite":
                d = Path(s.tenant_sqlite_dir)
                d.mkdir(parents=True, exist_ok=True)
                target = d / f"{db_name}.db"
                if target.exists():
                    suffix = secrets.token_hex(4)
                    db_name = f"{clean}_{suffix}"
                url = f"sqlite:///{(d / (db_name + '.db')).resolve().as_posix()}"
            else:
                url = self._provision_postgres(db_name)
        else:
            suffix = secrets.token_hex(6)
            db_name = f"ws_tenant_{suffix}"
            if s.tenant_db_mode == "sqlite":
                d = Path(s.tenant_sqlite_dir)
                d.mkdir(parents=True, exist_ok=True)
                url = f"sqlite:///{(d / (db_name + '.db')).resolve().as_posix()}"
            else:
                url = self._provision_postgres(db_name)
        eng = _make_engine(url)
        try:
            migrate_tenant(eng)
        except Exception:
            eng.dispose()
            self._drop_physical(db_name, url)
            raise
        eng.dispose()
        return db_name, encrypt(url)

    def _provision_postgres(self, db_name: str) -> str:
        s = get_settings()
        if not s.postgres_admin_url:
            raise RuntimeError("POSTGRES_ADMIN_URL is required when TENANT_DB_MODE=postgres")
        role = db_name  # same generated identifier
        password = secrets.token_urlsafe(24).replace("-", "a").replace("_", "b")  # alnum-only, safe to inline
        admin = create_engine(s.postgres_admin_url, isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as c:
                role_exists = c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
                if not role_exists:
                    c.execute(text(f'CREATE ROLE "{role}" LOGIN PASSWORD \'{password}\''))
                    # PG16+: a non-superuser CREATEROLE provisioner only gets ADMIN on roles it creates,
                    # not the right to SET ROLE to them, which CREATE DATABASE ... OWNER requires.
                    c.execute(text(f'GRANT "{role}" TO CURRENT_USER WITH SET TRUE'))
                else:
                    c.execute(text(f'ALTER ROLE "{role}" WITH PASSWORD \'{password}\''))

                db_exists = c.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": db_name}).scalar()
                if not db_exists:
                    c.execute(text(f'CREATE DATABASE "{db_name}" OWNER "{role}"'))
                    c.execute(text(f'REVOKE ALL ON DATABASE "{db_name}" FROM PUBLIC'))
        except Exception:
            # Don't leave a half-provisioned role/database behind (provision() only cleans up after migrate fails).
            self._drop_physical(db_name, "")
            raise
        finally:
            admin.dispose()
        return f"postgresql+psycopg://{role}:{password}@{s.tenant_db_host}:{s.tenant_db_port}/{db_name}"

    def _drop_physical(self, db_name: str, url: str) -> None:
        s = get_settings()
        try:
            if s.tenant_db_mode == "sqlite":
                Path(url.replace("sqlite:///", "")).unlink(missing_ok=True)
            elif s.postgres_admin_url:
                admin = create_engine(s.postgres_admin_url, isolation_level="AUTOCOMMIT")
                with admin.connect() as c:
                    c.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
                    c.execute(text(f'DROP ROLE IF EXISTS "{db_name}"'))
                admin.dispose()
        except Exception:
            log.exception("failed to clean up tenant database %s", db_name)

    def drop(self, company: Company) -> None:
        url = decrypt(company.db_url_encrypted)
        self.forget(company.id)
        self._drop_physical(company.db_name, url)


tenants = TenantManager()
