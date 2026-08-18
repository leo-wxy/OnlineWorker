from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from plugins.providers.builtin.codex.python import session_assets, session_package
from plugins.providers.builtin.codex.python.session_assets import (
    SessionAssetError,
    list_sessions,
    list_trash,
    repair_visibility,
    restore_sessions,
    trash_sessions,
)
from plugins.providers.builtin.codex.python.session_package import export_sessions, import_sessions


def _write_session(home, session_id="session-1", title="OnlineWorker", provider="old-provider", cwd="/tmp/project", source=None):
    path = home / "sessions" / "2026" / "08" / "18" / f"rollout-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    meta = {"id": session_id, "cwd": cwd, "model_provider": provider}
    if source is not None:
        meta["source"] = source
    rows = [
        {"timestamp": now, "type": "session_meta", "payload": meta},
        {"timestamp": now, "type": "event_msg", "payload": {"type": "token_count", "info": {"model": "gpt-test", "last_token_usage": {"input_tokens": 100, "cached_input_tokens": 20, "output_tokens": 30, "reasoning_output_tokens": 10, "total_tokens": 140}}}},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    (home / "session_index.jsonl").write_text(json.dumps({"id": session_id, "thread_name": title}) + "\n", encoding="utf-8")
    return path


def test_list_search_and_30_day_usage_are_local(tmp_path):
    home = tmp_path / "codex-home"
    _write_session(home)

    result = list_sessions(home)

    assert result["sessions"][0]["title"] == "OnlineWorker"
    assert result["usage30d"]["totalTokens"] == 140
    assert result["usage30d"]["cost"] == {"status": "unavailable"}
    assert list_sessions(home, query="missing")["sessions"] == []
    assert len(list_sessions(home, query="worker")["sessions"]) == 1


def test_fast_list_classifies_and_filters_session_kinds(tmp_path):
    home = tmp_path / "codex-home"
    _write_session(home, "conversation", "Main chat", cwd="/work/onlineworker")
    _write_session(home, "agent", "Helper", cwd="/work/onlineworker", source={"subagent": {"thread_spawn": {"parent_thread_id": "conversation"}}})
    (home / "session_index.jsonl").write_text(
        json.dumps({"id": "conversation", "thread_name": "Main chat"}) + "\n" + json.dumps({"id": "agent", "thread_name": "Helper"}) + "\n",
        encoding="utf-8",
    )

    conversations = list_sessions(home, include_usage=False)
    subagents = list_sessions(home, include_usage=False, kind="subagent")

    assert [item["sessionId"] for item in conversations["sessions"]] == ["conversation"]
    assert conversations["sessions"][0]["tokenSummary"] is None
    assert conversations["sessions"][0]["sessionKind"] == "conversation"
    assert subagents["sessions"][0]["sessionKind"] == "subagent"
    assert len(list_sessions(home, query="onlineworker", include_usage=False, kind="all")["sessions"]) == 2


def test_zip_round_trip_skip_and_conflict(tmp_path):
    source_home = tmp_path / "source-home"
    _write_session(source_home)
    archive = tmp_path / "sessions.zip"
    exported = export_sessions(source_home, ["session-1"], archive)
    assert exported["count"] == 1

    target_home = tmp_path / "target-home"
    imported = import_sessions(target_home, archive)
    assert imported["items"] == [{"sessionId": "session-1", "status": "imported"}]
    assert import_sessions(target_home, archive)["items"] == [{"sessionId": "session-1", "status": "skipped"}]
    target = next((target_home / "sessions").rglob("*.jsonl"))
    target.write_text(target.read_text() + "{}\n", encoding="utf-8")
    assert import_sessions(target_home, archive)["items"] == [{"sessionId": "session-1", "status": "conflict"}]


def test_trash_restore_and_quick_visibility_repair(tmp_path):
    home = tmp_path / "codex-home"
    plugin_root = tmp_path / "plugin-data"
    rollout = _write_session(home)
    trashed = trash_sessions(plugin_root, home, ["session-1"])
    assert trashed["count"] == 1
    assert not rollout.exists()
    assert list_trash(plugin_root)[0]["sessionId"] == "session-1"
    assert restore_sessions(plugin_root, home, ["session-1"])["count"] == 1
    assert rollout.exists()

    (home / "config.toml").write_text('model_provider = "openai-test"\n', encoding="utf-8")
    db = home / "state_5.sqlite"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, model_provider TEXT, rollout_path TEXT, updated_at INTEGER)")
    connection.execute("INSERT INTO threads VALUES (?, ?, ?, ?)", ("session-1", "old-provider", str(rollout), 7))
    connection.commit()
    connection.close()

    repaired = repair_visibility(home)
    assert repaired == {"provider": "openai-test", "rowsChanged": 1, "rolloutsChanged": 1}
    connection = sqlite3.connect(db)
    assert connection.execute("SELECT model_provider, updated_at FROM threads").fetchone() == ("openai-test", 7)
    connection.close()
    first = json.loads(rollout.read_text().splitlines()[0])
    assert first["payload"]["model_provider"] == "openai-test"


def test_unknown_session_does_not_remove_index_entry(tmp_path):
    home = tmp_path / "codex-home"
    plugin_root = tmp_path / "plugin-data"
    rollout = _write_session(home)
    index = home / "session_index.jsonl"
    index.write_text(index.read_text() + json.dumps({"id": "stale", "thread_name": "stale"}) + "\n", encoding="utf-8")
    before = index.read_bytes()

    assert trash_sessions(plugin_root, home, ["stale"]) == {"trashed": [], "count": 0}
    assert index.read_bytes() == before
    assert rollout.exists()


def test_restore_rejects_tampered_trash_path(tmp_path):
    home = tmp_path / "codex-home"
    plugin_root = tmp_path / "plugin-data"
    rollout = _write_session(home)
    trash_sessions(plugin_root, home, ["session-1"])
    manifest_path = next((plugin_root / "session-trash").glob("*/manifest.json"))
    manifest = json.loads(manifest_path.read_text())
    manifest["sessions"][0]["trash_file"] = "../../outside.jsonl"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(SessionAssetError, match="unsafe_session_path"):
        restore_sessions(plugin_root, home, ["session-1"])

    assert not rollout.exists()
    assert len(list_trash(plugin_root)) == 1


def test_restore_rolls_back_all_files_when_one_move_fails(tmp_path, monkeypatch):
    home = tmp_path / "codex-home"
    plugin_root = tmp_path / "plugin-data"
    first = _write_session(home, "session-1", "one")
    second = _write_session(home, "session-2", "two")
    (home / "session_index.jsonl").write_text(
        json.dumps({"id": "session-1", "thread_name": "one"}) + "\n" + json.dumps({"id": "session-2", "thread_name": "two"}) + "\n",
        encoding="utf-8",
    )
    trash_sessions(plugin_root, home, ["session-1", "session-2"])
    original_utime = session_assets.os.utime
    calls = 0

    def fail_second(path, *, ns):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fixture")
        original_utime(path, ns=ns)

    monkeypatch.setattr(session_assets.os, "utime", fail_second)
    with pytest.raises(SessionAssetError, match="restore_failed"):
        restore_sessions(plugin_root, home, ["session-1", "session-2"])

    assert not first.exists() and not second.exists()
    assert {item["sessionId"] for item in list_trash(plugin_root)} == {"session-1", "session-2"}


def test_zip_import_rejects_excess_total_uncompressed_size(tmp_path, monkeypatch):
    source_home = tmp_path / "source-home"
    _write_session(source_home)
    archive = tmp_path / "sessions.zip"
    export_sessions(source_home, ["session-1"], archive)
    monkeypatch.setattr(session_package, "MAX_TOTAL_BYTES", 1)

    with pytest.raises(SessionAssetError, match="invalid_package"):
        import_sessions(tmp_path / "target-home", archive)
