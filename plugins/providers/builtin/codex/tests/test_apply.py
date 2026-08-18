from __future__ import annotations

import json

import pytest

from plugins.providers.builtin.codex.python import apply as apply_module
from plugins.providers.builtin.codex.python.account_store import AccountStore
from plugins.providers.builtin.codex.python.apply import ApplyError, apply_account, refresh_current
from plugins.providers.builtin.codex.python.compat import parse_cockpit_tools


def _record():
    return parse_cockpit_tools(
        {
            "id_token": "id-token",
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "account_id": "acct-apply",
            "last_refresh": "2026-08-18T00:00:00Z",
            "email": "apply@example.com",
            "type": "codex",
            "expired": "",
        }
    ).records[0]


def test_import_is_separate_and_apply_writes_real_codex_shape(account_store_root, tmp_path):
    store = AccountStore(account_store_root)
    record = _record()
    store.upsert(record)
    home = tmp_path / "codex-home"
    assert not (home / "auth.json").exists()

    apply_account(store, record.identity_key, home=home)

    auth = json.loads((home / "auth.json").read_text())
    assert auth["tokens"]["account_id"] == "acct-apply"
    assert auth["OPENAI_API_KEY"] is None
    current = refresh_current(store, home=home)
    assert current["state"] == "matched"
    assert store.list_redacted(current["accountId"])[0]["isCurrent"] is True


def test_current_account_can_be_reapplied(account_store_root, tmp_path):
    store = AccountStore(account_store_root)
    record = _record()
    store.upsert(record)
    home = tmp_path / "codex-home"
    apply_account(store, record.identity_key, home=home)
    auth = json.loads((home / "auth.json").read_text())
    auth["stale"] = True
    (home / "auth.json").write_text(json.dumps(auth), encoding="utf-8")

    apply_account(store, record.identity_key, home=home)

    assert "stale" not in json.loads((home / "auth.json").read_text())
    current = refresh_current(store, home=home)
    assert store.list_redacted(current["accountId"])[0]["isCurrent"] is True


def test_apply_failure_restores_auth(account_store_root, tmp_path, monkeypatch):
    store = AccountStore(account_store_root)
    record = _record()
    store.upsert(record)
    home = tmp_path / "codex-home"
    home.mkdir()
    auth = home / "auth.json"
    auth.write_bytes(b'{"before":true}')
    old_index = store.index_bytes()
    real_atomic_write = apply_module.atomic_write
    failed = False

    def fail_after_auth_write(path, raw, **kwargs):
        nonlocal failed
        real_atomic_write(path, raw, **kwargs)
        if not failed:
            failed = True
            raise OSError("fixture")

    monkeypatch.setattr(apply_module, "atomic_write", fail_after_auth_write)

    with pytest.raises(ApplyError) as error:
        apply_account(store, record.identity_key, home=home)

    assert error.value.rolled_back is True
    assert auth.read_bytes() == b'{"before":true}'
    assert store.index_bytes() == old_index


def test_malformed_auth_is_unmanaged(account_store_root, tmp_path):
    store = AccountStore(account_store_root)
    store.upsert(_record())
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "auth.json").write_text("{", encoding="utf-8")

    assert refresh_current(store, home=home)["state"] == "unmanaged"
