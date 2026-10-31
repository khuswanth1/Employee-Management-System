import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

# Environment must be set before the app (and its cached settings) is imported.
_tmp = Path(tempfile.mkdtemp(prefix="worksphere-tests-"))
# Opt-in Postgres tenants: set TEST_POSTGRES_ADMIN_URL (+ TEST_TENANT_DB_HOST/PORT). Default stays SQLite.
_pg_admin = os.environ.get("TEST_POSTGRES_ADMIN_URL", "")
os.environ.update(
    ENVIRONMENT="test",  # never "development": dev mode relaxes login and the rate limiter
    SECRET_KEY="test-secret-key-test-secret-key-0123456789",
    ENCRYPTION_KEY=Fernet.generate_key().decode(),
    PLATFORM_DATABASE_URL=f"sqlite:///{(_tmp / 'platform.db').as_posix()}",
    TENANT_DB_MODE="postgres" if _pg_admin else "sqlite",
    POSTGRES_ADMIN_URL=_pg_admin,
    TENANT_DB_HOST=os.environ.get("TEST_TENANT_DB_HOST", "db"),
    TENANT_DB_PORT=os.environ.get("TEST_TENANT_DB_PORT", "5432"),
    TENANT_SQLITE_DIR=str(_tmp / "tenants"),
    UPLOAD_DIR=str(_tmp / "uploads"),
    BACKUP_DIR=str(_tmp / "backups"),
    BOOTSTRAP_ADMIN_EMAIL="admin@platform.com",
    BOOTSTRAP_ADMIN_PASSWORD="Platform-Admin-1",
    WEBHOOK_WORKER_INTERVAL_SECONDS="3600",
    # Pin everything a developer's local backend/.env could change, so the suite is hermetic.
    WEBHOOK_ALLOW_PRIVATE_URLS="false",
    SMTP_HOST="",
    TURN_URL="",
    TURN_SECRET="",
    TURN_USERNAME="",
    STUN_URLS="stun:stun.l.google.com:19302",
    ACCESS_TOKEN_MINUTES="30",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.ratelimit import login_limiter, reset_request_limiter, token_confirm_limiter  # noqa: E402
from app.main import app  # noqa: E402

PW = "Str0ng-Pw-12"
ADMIN = ("admin@platform.com", "Platform-Admin-1")


class Api:
    """Thin helper over TestClient for readable tests."""

    def __init__(self, client: TestClient):
        self.c = client
        self._admin_token: str | None = None

    @staticmethod
    def h(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def admin_token(self) -> str:
        if not self._admin_token:
            r = self.c.post("/api/v1/auth/platform/login", json={"email": ADMIN[0], "password": ADMIN[1]})
            assert r.status_code == 200, r.text
            self._admin_token = r.json()["access_token"]
        return self._admin_token

    def make_company(self, slug: str, founder_email: str | None = None) -> dict:
        r = self.c.post("/api/v1/platform/companies", headers=self.h(self.admin_token()), json={
            "name": slug.title(), "slug": slug, "founder_name": "Founder " + slug,
            "founder_email": founder_email or f"founder@{slug}.com", "founder_password": PW,
        })
        assert r.status_code == 201, r.text
        return r.json()

    def ensure_company(self, slug: str) -> None:
        r = self.c.post("/api/v1/auth/login", json={"company_slug": slug, "email": f"founder@{slug}.com", "password": PW})
        if r.status_code != 200:
            self.make_company(slug)

    def login(self, slug: str, email: str, password: str = PW) -> str:
        r = self.c.post("/api/v1/auth/login", json={"company_slug": slug, "email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    def add_user(self, founder_token: str, email: str, role: str = "employee", **extra) -> dict:
        body = {"email": email, "full_name": email.split("@")[0].title() + " Test", "password": PW, "role": role, **extra}
        r = self.c.post("/api/v1/employees", headers=self.h(founder_token), json=body)
        assert r.status_code == 201, r.text
        return r.json()

    def get(self, token, url, **kw):
        return self.c.get("/api/v1" + url, headers=self.h(token), **kw)

    def post(self, token, url, json=None, **kw):
        return self.c.post("/api/v1" + url, headers=self.h(token), json=json, **kw)

    def patch(self, token, url, json=None):
        return self.c.patch("/api/v1" + url, headers=self.h(token), json=json)

    def put(self, token, url, json=None):
        return self.c.put("/api/v1" + url, headers=self.h(token), json=json)

    def delete(self, token, url):
        return self.c.delete("/api/v1" + url, headers=self.h(token))


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def api(client):
    return Api(client)


@pytest.fixture(autouse=True)
def _reset_limiter():
    for lim in (login_limiter, reset_request_limiter, token_confirm_limiter):
        lim.clear()
    yield


@pytest.fixture(scope="session")
def org(api):
    """A fully populated company: one user of each role, reused across tests (read-mostly)."""
    api.make_company("acme")
    f = api.login("acme", "founder@acme.com")
    hr = api.add_user(f, "hr@acme.com", "hr")
    mgr = api.add_user(f, "mgr@acme.com", "manager")
    emp = api.add_user(f, "emp@acme.com", "employee", manager_id=mgr["id"])
    emp2 = api.add_user(f, "emp2@acme.com", "employee", manager_id=mgr["id"])
    other_mgr = api.add_user(f, "mgr2@acme.com", "manager")
    return {
        "slug": "acme",
        "founder": f,
        "hr": api.login("acme", "hr@acme.com"),
        "mgr": api.login("acme", "mgr@acme.com"),
        "emp": api.login("acme", "emp@acme.com"),
        "emp2": api.login("acme", "emp2@acme.com"),
        "mgr2": api.login("acme", "mgr2@acme.com"),
        "ids": {"hr": hr["id"], "mgr": mgr["id"], "emp": emp["id"], "emp2": emp2["id"], "mgr2": other_mgr["id"]},
    }
