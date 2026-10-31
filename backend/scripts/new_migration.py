"""Autogenerate the next Alembic revision from the SQLAlchemy models.

    python scripts/new_migration.py tenant "add task labels"
    python scripts/new_migration.py platform "add company plan"

It diffs the models against a scratch SQLite database that has been upgraded to the current head,
so the generated file only contains what changed. Review the file before committing it.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alembic import command  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from app.tenancy.manager import _alembic_cfg  # noqa: E402


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("tenant", "platform"):
        sys.exit(__doc__)
    kind, message = sys.argv[1], sys.argv[2]
    engine = create_engine("sqlite:///" + os.path.join(tempfile.mkdtemp(), "scratch.db"))
    cfg = _alembic_cfg(kind, engine=engine)
    command.upgrade(cfg, "head")
    command.revision(cfg, message=message, autogenerate=True)


if __name__ == "__main__":
    main()
