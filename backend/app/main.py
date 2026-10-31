import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.core import redis_client
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, new_request_id
from app.core.security import hash_password, validate_password_strength
from app.db.platform_models import Company, PlatformUser
from app.db.session import get_platform_engine, platform_session
from app.modules.admin.router import router as admin_router
from app.modules.attendance.corrections import router as attendance_corrections_router
from app.modules.attendance.router import router as attendance_router
from app.modules.attendance.shifts import router as attendance_shifts_router
from app.modules.board.router import router as board_router
from app.modules.chat.router import router as chat_router
from app.modules.auth.account import router as account_router
from app.modules.auth.router import router as auth_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.employees.lifecycle import router as employee_lifecycle_router
from app.modules.employees.profile import router as employee_profile_router
from app.modules.employees.router import router as employees_router
from app.modules.escalations.router import router as escalations_router
from app.modules.leave.router import router as leave_router
from app.modules.meetings.router import router as meetings_router
from app.modules.notifications.router import router as notifications_router
from app.modules.org.router import router as org_router
from app.modules.payroll.router import router as payroll_router
from app.modules.performance.router import router as performance_router
from app.modules.platform.router import router as platform_router
from app.modules.projects.router import router as projects_router
from app.modules.teams.router import router as teams_router
from app.modules.todos.router import router as todos_router
from app.modules.updates.router import router as updates_router
from app.modules.webhooks.router import router as webhooks_router
from app.modules.webhooks.service import process_due
from app import realtime
from app.tenancy.manager import migrate_platform, migrate_tenant, tenants

log = logging.getLogger("worksphere")


def bootstrap_platform() -> None:
    s = get_settings()
    migrate_platform(get_platform_engine())
    if s.bootstrap_admin_email and s.bootstrap_admin_password:
        with platform_session() as db:
            admin = db.scalar(select(PlatformUser).where(PlatformUser.email == s.bootstrap_admin_email.lower()))
            if admin is None:
                if s.environment == "production":
                    validate_password_strength(s.bootstrap_admin_password)  # raises: refuse to start with a weak first password
                db.add(PlatformUser(email=s.bootstrap_admin_email.lower(), full_name="Platform Admin",
                                    password_hash=hash_password(s.bootstrap_admin_password)))
                db.commit()
                log.info("bootstrap platform admin created")
            else:
                # Never overwrite: a password the admin changed (or MFA they enabled) must survive a restart.
                # To reset one deliberately use `python scripts/reset_platform_admin_password.py <email>`.
                log.info("bootstrap platform admin already exists; credentials left unchanged")
    with platform_session() as db:
        for c in db.scalars(select(Company)):
            log.info("Checking tenant: id=%s slug=%s", c.id, c.slug)
            try:
                t_eng = tenants.engine_for(c)
                from sqlalchemy import inspect, text
                with t_eng.connect() as t_conn:
                    insp = inspect(t_conn)
                    t_names = insp.get_table_names()
                    ver = t_conn.execute(text("SELECT version_num FROM alembic_version")).scalar() if "alembic_version" in t_names else None
                    if "_alembic_tmp_users" in t_names:
                        t_conn.execute(text("DROP TABLE _alembic_tmp_users"))
                        t_conn.commit()
                    if "conversations" in t_names and ver == "0001":
                        t_conn.execute(text("UPDATE alembic_version SET version_num = '0002'"))
                        t_conn.commit()
                        log.info("Tenant %s alembic_version synchronized to '0002'", c.slug)
                migrate_tenant(t_eng)
                db.commit()
                log.info("tenant %s schema migrated to head", c.slug)
            except Exception as e:
                if "does not exist" in str(e):
                    log.warning("Tenant '%s' (id=%d) database '%s' does not exist in PostgreSQL (orphaned company record).", c.slug, c.id, c.db_name)
                else:
                    log.exception("tenant migration failed on startup", extra={"tenant_id": c.id, "slug": c.slug})


def _deliver_all() -> None:
    token = redis_client.acquire_lock("webhook-worker", ttl_seconds=60)
    if token is None:
        return  # another instance is delivering this round
    try:
        _deliver_all_locked()
    finally:
        redis_client.release_lock("webhook-worker", token)


def _deliver_all_locked() -> None:
    with platform_session() as pdb:
        companies = [c for c in pdb.scalars(select(Company).where(Company.status == "active"))]
        pdb.expunge_all()
    for c in companies:
        try:
            with tenants.session_for(c) as db:
                process_due(db)
        except Exception:
            log.exception("webhook worker failed", extra={"tenant_id": c.id})


async def _webhook_worker() -> None:
    interval = get_settings().webhook_worker_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            await run_in_threadpool(_deliver_all)
        except Exception:
            log.exception("webhook worker loop error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await run_in_threadpool(bootstrap_platform)
    task = asyncio.create_task(_webhook_worker())
    subscriber = asyncio.create_task(realtime.bridge.run()) if redis_client.enabled() else None
    yield
    task.cancel()
    if subscriber:
        subscriber.cancel()
    tenants.dispose_all()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="WorkSphere API",
        version="1.0.0",
        description="Multi-tenant employee & project management. Tenant is resolved from the JWT only.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        rid = new_request_id()
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        log.info("request", extra={"path": request.url.path, "status": response.status_code,
                                   "duration_ms": round((time.perf_counter() - start) * 1000, 1)})
        return response

    install_error_handlers(app)

    api = APIRouter(prefix="/api/v1")
    for r in (auth_router, account_router, platform_router, employees_router, employee_profile_router, employee_lifecycle_router, projects_router, updates_router, leave_router,
              attendance_router, attendance_corrections_router, attendance_shifts_router, payroll_router, performance_router, dashboard_router, notifications_router, webhooks_router, meetings_router, chat_router, org_router, board_router, escalations_router, teams_router, todos_router, admin_router):
        api.include_router(r)
    app.include_router(api)

    @app.get("/api/health", tags=["health"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()
