from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
_factory: sessionmaker | None = None


def get_platform_engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        url = get_settings().platform_database_url
        kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _fk_on(dbapi_conn, _):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        _factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def platform_session() -> Session:
    get_platform_engine()
    assert _factory is not None
    return _factory()


def reset_platform_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None
