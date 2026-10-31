"""Break-glass: switch off two-step verification for one platform administrator (lost phone and recovery codes).

Needs shell access to the server and its .env, which is the same trust level as the database itself.
Usage:  python scripts/reset_platform_mfa.py admin@example.com
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.db.platform_models import PlatformUser  # noqa: E402
from app.db.session import platform_session  # noqa: E402


def main(email: str) -> int:
    with platform_session() as db:
        admin = db.scalar(select(PlatformUser).where(func.lower(PlatformUser.email) == email.lower()))
        if admin is None:
            print("No such platform administrator")
            return 1
        admin.mfa_enabled, admin.mfa_secret_enc, admin.mfa_last_step, admin.mfa_recovery = False, None, None, None
        admin.session_version = (admin.session_version or 0) + 1
        db.commit()
    print("Two-step verification switched off and all sessions ended. Sign in and set it up again.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
