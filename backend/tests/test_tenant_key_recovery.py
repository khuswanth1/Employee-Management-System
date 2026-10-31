"""B-006: a tenant DB URL that cannot be decrypted must stop the tenant from opening outside development."""
from types import SimpleNamespace

import pytest

from app.tenancy import manager as mgr


def _company(tmp_path, name="acme_recover"):
    (tmp_path / f"{name}.db").write_bytes(b"")
    return SimpleNamespace(id=987654, slug="recover", db_name=name, db_url_encrypted="not-a-valid-token")


def _settings(env, tmp_path):
    return SimpleNamespace(environment=env, tenant_db_mode="sqlite", tenant_sqlite_dir=str(tmp_path))


@pytest.fixture()
def fresh_manager(monkeypatch):
    m = mgr.TenantManager()
    monkeypatch.setattr(mgr, "_make_engine", lambda url: SimpleNamespace(url=url))
    return m


@pytest.mark.parametrize("env", ["production", "staging", "test"])
def test_wrong_key_is_an_error_outside_development(monkeypatch, tmp_path, fresh_manager, env):
    monkeypatch.setattr(mgr, "get_settings", lambda: _settings(env, tmp_path))
    c = _company(tmp_path)
    with pytest.raises(Exception):
        fresh_manager.engine_for(c)
    assert c.db_url_encrypted == "not-a-valid-token", "the stored URL must not be rewritten"


def test_development_may_still_recover_a_local_sqlite_file(monkeypatch, tmp_path, fresh_manager):
    monkeypatch.setattr(mgr, "get_settings", lambda: _settings("development", tmp_path))
    c = _company(tmp_path)
    eng = fresh_manager.engine_for(c)
    assert eng.url.startswith("sqlite:///") and c.db_url_encrypted != "not-a-valid-token"
