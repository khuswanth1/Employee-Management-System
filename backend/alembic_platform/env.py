from alembic import context
from sqlalchemy import create_engine, pool

from app.db import platform_models  # noqa: F401  (register tables)
from app.db.base import PlatformBase

config = context.config
target_metadata = PlatformBase.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = config.attributes.get("engine")
    own = engine is None
    if own:
        engine = create_engine(config.get_main_option("sqlalchemy.url"), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.commit()  # end the autobegun transaction so begin() below is legal (SQLAlchemy 2.1)
            with connection.begin():
                context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
                context.run_migrations()
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()
    finally:
        if own:
            engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
