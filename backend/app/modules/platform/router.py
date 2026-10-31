import logging
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound
from app.core.security import decrypt
from app.db.platform_models import Company
from app.db.tenant_models import AuditLog, Project, Task, User
from app.deps import get_platform_admin
from app.modules.platform.schemas import CompanyCreate, CompanyOut, CompanyUpdate
from app.realtime import manager
from app.tenancy.manager import migrate_tenant, tenants
from app.tenancy.seed import seed_tenant

log = logging.getLogger("worksphere.platform")
router = APIRouter(prefix="/platform", tags=["platform"])


def _out(c: Company) -> dict:
    return CompanyOut(id=c.id, slug=c.slug, name=c.name, status=c.status, max_users=c.max_users, created_at=c.created_at).model_dump()


def _get(pdb, company_id: int) -> Company:
    c = pdb.get(Company, company_id)
    if c is None:
        raise NotFound("Company not found")
    return c


@router.post("/companies", status_code=201)
def create_company(body: CompanyCreate, admin=Depends(get_platform_admin)):
    _, pdb = admin
    if pdb.scalar(select(Company.id).where(Company.slug == body.slug)):
        raise Conflict("A company with this URL name already exists")
    db_name, enc_url = tenants.provision(slug=body.slug)
    company = Company(slug=body.slug, name=body.name, db_name=db_name, db_url_encrypted=enc_url, max_users=body.max_users)
    try:
        pdb.add(company)
        pdb.flush()
        with tenants.session_for(company) as tdb:
            seed_tenant(tdb, founder_email=body.founder_email, founder_name=body.founder_name, founder_password=body.founder_password)
        pdb.commit()
    except Exception:
        pdb.rollback()
        tenants.drop(company)
        raise
    log.info("tenant provisioned", extra={"tenant_id": company.id})
    return _out(company)


@router.get("/companies")
def list_companies(admin=Depends(get_platform_admin)):
    _, pdb = admin
    return {"items": [_out(c) for c in pdb.scalars(select(Company).order_by(Company.id))]}


@router.get("/companies/{company_id}")
def get_company(company_id: int, admin=Depends(get_platform_admin)):
    return _out(_get(admin[1], company_id))


@router.patch("/companies/{company_id}")
def update_company(company_id: int, body: CompanyUpdate, admin=Depends(get_platform_admin)):
    _, pdb = admin
    c = _get(pdb, company_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    pdb.commit()
    return _out(c)


@router.delete("/companies/{company_id}", status_code=204)
def delete_company(company_id: int, admin=Depends(get_platform_admin)):
    _, pdb = admin
    c = _get(pdb, company_id)
    try:
        tenants.drop(c)
    except Exception:
        log.warning("failed to drop physical tenant database, proceeding to delete company record", extra={"tenant_id": c.id})
    pdb.delete(c)
    pdb.commit()
    return None


@router.get("/companies/{company_id}/usage")
def usage(company_id: int, admin=Depends(get_platform_admin)):
    _, pdb = admin
    c = _get(pdb, company_id)
    with tenants.session_for(c) as db:
        data = {
            "users": db.scalar(select(func.count(User.id))),
            "active_users": db.scalar(select(func.count(User.id)).where(User.is_active.is_(True))),
            "projects": db.scalar(select(func.count(Project.id))),
            "tasks": db.scalar(select(func.count(Task.id))),
            "audit_events": db.scalar(select(func.count(AuditLog.id))),
        }
    s = get_settings()
    if s.tenant_db_mode == "sqlite":
        path = Path(decrypt(c.db_url_encrypted).replace("sqlite:///", ""))
        data["db_size_bytes"] = path.stat().st_size if path.exists() else 0
    else:
        with tenants.session_for(c) as db:
            data["db_size_bytes"] = db.scalar(text("SELECT pg_database_size(current_database())"))
    data["online_users"] = manager.online_count(c.id)
    data["max_users"] = c.max_users
    return data


@router.post("/companies/{company_id}/backup")
def backup(company_id: int, admin=Depends(get_platform_admin)):
    _, pdb = admin
    c = _get(pdb, company_id)
    s = get_settings()
    out_dir = Path(s.backup_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    url = decrypt(c.db_url_encrypted)
    if s.tenant_db_mode == "sqlite":
        dest = out_dir / f"{c.slug}-{stamp}.db"
        src = sqlite3.connect(url.replace("sqlite:///", ""))
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
    else:
        if not shutil.which("pg_dump"):
            raise AppError("pg_dump is not available on the server", status_code=501)
        u = make_url(url)
        dest = out_dir / f"{c.slug}-{stamp}.dump"
        env = {**__import__("os").environ, "PGPASSWORD": u.password or ""}  # full env: Windows needs SYSTEMROOT
        r = subprocess.run(
            ["pg_dump", "-Fc", "-h", u.host, "-p", str(u.port or 5432), "-U", u.username, "-f", str(dest), u.database],
            env=env, capture_output=True, timeout=600,
        )
        if r.returncode != 0:
            log.error("pg_dump failed: %s", r.stderr.decode()[:500])
            raise AppError("Backup failed", status_code=500)
    return {"file": dest.name, "size_bytes": dest.stat().st_size}


@router.post("/migrate")
def migrate_all(admin=Depends(get_platform_admin)):
    """Upgrade every tenant database to the latest schema revision."""
    _, pdb = admin
    done, failed = [], []
    for c in pdb.scalars(select(Company)):
        try:
            migrate_tenant(tenants.engine_for(c))
            done.append(c.slug)
        except Exception:
            log.exception("tenant migration failed", extra={"tenant_id": c.id})
            failed.append(c.slug)
    return {"migrated": done, "failed": failed}


@router.get("/stats")
def stats(admin=Depends(get_platform_admin)):
    _, pdb = admin
    rows = dict(pdb.execute(select(Company.status, func.count(Company.id)).group_by(Company.status)).all())
    return {"companies": sum(rows.values()), "active": rows.get("active", 0), "suspended": rows.get("suspended", 0)}
