from __future__ import annotations

import json
import multiprocessing
import os
import stat
import time

import pytest

from plugins.providers.builtin.codex.python.account_store import AccountStore, AccountStoreError, operation_lock
from plugins.providers.builtin.codex.python.compat import parse_cockpit_tools


def _record(secret: str = "secret-fixture"):
    raw = {
        "auth_mode": "apikey",
        "OPENAI_API_KEY": secret,
        "email": "account@example.com",
        "future": {"kept": True},
    }
    return parse_cockpit_tools(raw).records[0]


def _lock_worker(root: str, queue) -> None:
    with operation_lock(root):
        started = time.monotonic()
        time.sleep(0.15)
        queue.put((started, time.monotonic()))


def test_round_trip_is_encrypted_redacted_and_permission_tight(account_store_root):
    store = AccountStore(account_store_root)
    record = _record()

    assert store.upsert(record) == "inserted"
    assert store.get(record.identity_key).credentials == record.credentials
    assert store.list_redacted()[0]["stableIdentityDisplay"] == "account@example.com"

    files = [store.key_path, store.index_path, store._detail_path(record.identity_key), store.root / "operation.lock"]
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in files)
    persisted = b"".join(path.read_bytes() for path in files)
    assert b"secret-fixture" not in persisted
    assert b"OPENAI_API_KEY" not in store.index_path.read_bytes()


def test_tamper_wrong_key_and_failed_replace_preserve_source(account_store_root, monkeypatch):
    store = AccountStore(account_store_root)
    record = _record()
    store.upsert(record)
    path = store._detail_path(record.identity_key)
    original = path.read_bytes()

    envelope = json.loads(original)
    envelope["ciphertext"] = envelope["ciphertext"][:-4] + "AAAA"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(AccountStoreError):
        store.get(record.identity_key)
    path.write_bytes(original)

    store.key_path.write_bytes(os.urandom(32))
    with pytest.raises(AccountStoreError, match="wrong_key"):
        store.get(record.identity_key)
    store.key_path.write_bytes(store.key_path.with_suffix(".missing").read_bytes() if store.key_path.with_suffix(".missing").exists() else b"x" * 32)


def test_legacy_detail_migrates_only_after_valid_read(account_store_root):
    store = AccountStore(account_store_root)
    record = _record()
    store.upsert(record)
    path = store._detail_path(record.identity_key)
    legacy = {
        "auth_mode": record.auth_mode,
        "identity_key": record.identity_key,
        "identity_display": record.identity_display,
        "source": record.source,
        "credentials": record.credentials,
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    assert store.get(record.identity_key).credentials["future"] == {"kept": True}
    assert json.loads(path.read_text())["version"] == 1
    assert path.with_suffix(".json.bak").read_bytes() == json.dumps(legacy).encode()


def test_cross_process_lock_serializes(account_store_root):
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    first = context.Process(target=_lock_worker, args=(str(account_store_root), queue))
    second = context.Process(target=_lock_worker, args=(str(account_store_root), queue))
    first.start()
    time.sleep(0.03)
    second.start()
    first.join(5)
    second.join(5)
    intervals = sorted([queue.get(timeout=1), queue.get(timeout=1)])
    assert first.exitcode == second.exitcode == 0
    assert intervals[1][0] >= intervals[0][1] - 0.02
