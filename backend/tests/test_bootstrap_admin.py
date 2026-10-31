"""The bootstrap platform admin is created once; later starts never overwrite what the admin changed."""
import pytest
from sqlalchemy import select

from app import main
from app.core.security import hash_password, verify_password
from app.db.platform_models import PlatformUser
from app.db.session import platform_session

EMAIL = "bootstrap-once@platform.com"


@pytest.fixture
def boot(monkeypatch):
    def run(password="First-Passw0rd", environment="test"):
        s = main.get_settings().model_copy(update={"bootstrap_admin_email": EMAIL, "bootstrap_admin_password": password, "environment": environment})
        monkeypatch.setattr(main, "get_settings", lambda: s)
        main.bootstrap_platform()
    yield run
    with platform_session() as db:
        for u in db.scalars(select(PlatformUser).where(PlatformUser.email == EMAIL)):
            db.delete(u)
        db.commit()


def admin_row():
    with platform_session() as db:
        u = db.scalar(select(PlatformUser).where(PlatformUser.email == EMAIL))
        return None if u is None else (u.password_hash, u.is_active)


def test_created_once_and_never_overwritten_on_restart(boot):
    boot()
    first_hash, active = admin_row()
    assert active and verify_password("First-Passw0rd", first_hash)
    with platform_session() as db:                       # the admin changes their own password, and later is deactivated
        u = db.scalar(select(PlatformUser).where(PlatformUser.email == EMAIL))
        u.password_hash, u.is_active = hash_password("Changed-Passw0rd"), False
        db.commit()
    boot()                                               # restart with the same environment value
    h, active = admin_row()
    assert verify_password("Changed-Passw0rd", h) and not verify_password("First-Passw0rd", h)
    assert active is False                               # a deactivated admin is not silently re-enabled either


def test_production_refuses_a_weak_first_password(boot):
    with pytest.raises(ValueError):
        boot(password="weak", environment="production")
    assert admin_row() is None
    boot(password="Strong-Passw0rd", environment="production")
    assert admin_row() is not None


def test_reset_script_sets_password_and_ends_sessions(monkeypatch, boot):
    import importlib.util, pathlib
    boot()
    spec = importlib.util.spec_from_file_location("reset_pw", pathlib.Path(__file__).parent.parent / "scripts" / "reset_platform_admin_password.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    answers = iter(["Another-Passw0rd", "Another-Passw0rd"])
    monkeypatch.setattr(mod.getpass, "getpass", lambda *_: next(answers))
    with platform_session() as db:
        before = db.scalar(select(PlatformUser.session_version).where(PlatformUser.email == EMAIL))
    assert mod.main(EMAIL) == 0
    h, active = admin_row()
    assert verify_password("Another-Passw0rd", h) and active
    with platform_session() as db:
        assert db.scalar(select(PlatformUser.session_version).where(PlatformUser.email == EMAIL)) == (before or 0) + 1
    monkeypatch.setattr(mod.getpass, "getpass", lambda *_: "weak")
    assert mod.main(EMAIL) == 1
