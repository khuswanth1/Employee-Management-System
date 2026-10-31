"""Break-glass: set a new password for one platform administrator and end all their sessions.

The server no longer re-applies BOOTSTRAP_ADMIN_PASSWORD on every start, so this is the deliberate way to reset it.
Needs shell access to the server and its .env (the same trust level as the database itself).
The password is read from the prompt, never from the command line, so it stays out of shell history.
Usage:  python scripts/reset_platform_admin_password.py admin@example.com
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.core.security import hash_password, validate_password_strength  # noqa: E402
from app.db.platform_models import PlatformUser  # noqa: E402
from app.db.session import platform_session  # noqa: E402


def main(email: str) -> int:
    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat it: "):
        print("The two entries differ")
        return 1
    try:
        validate_password_strength(password)
    except ValueError as e:
        print(e)
        return 1
    with platform_session() as db:
        admin = db.scalar(select(PlatformUser).where(func.lower(PlatformUser.email) == email.lower()))
        if admin is None:
            print("No such platform administrator")
            return 1
        admin.password_hash = hash_password(password)
        admin.is_active = True
        admin.session_version = (admin.session_version or 0) + 1
        db.commit()
    print("Password changed and all sessions ended.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
