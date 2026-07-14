from bot.handlers.workspace import make_thread_open_callback_data
from bot.handlers.workspace_helpers import (
    THREAD_OPEN_V2_PREFIX,
    build_history_sync_batches,
    format_history_turn_message,
    get_workspace_callback_identity,
    history_turn_signature,
    make_thread_open_token,
    make_thread_topic_name,
    normalize_history_turn_timestamp,
    normalize_workspace_topic_label,
)
from core.storage import WorkspaceInfo


def test_normalize_workspace_topic_label_handles_empty_root_and_path():
    assert normalize_workspace_topic_label("") == "workspace"
    assert normalize_workspace_topic_label("/") == "root"
    assert normalize_workspace_topic_label("/Users/example/Projects/sample-workspace/") == "sample-workspace"
    assert normalize_workspace_topic_label("sample-workspace") == "sample-workspace"


def test_make_thread_topic_name_collapses_preview_and_limits_length():
    name = make_thread_topic_name(
        "codex",
        "onlineWorker",
        "第一行\n第二行\t" + ("x" * 200),
        "thread-id",
    )

    assert name.startswith("[codex/onlineWorker] 第一行 第二行 ")
    assert len(name) == 128


def test_make_thread_open_token_and_callback_data_are_stable():
    ws_id = "codex:/Users/example/Projects/sample-workspace"
    thread_id = "00000000-0000-7000-8000-000000000005"

    assert make_thread_open_token(thread_id) == make_thread_open_token(thread_id)
    assert len(make_thread_open_token(thread_id)) == 16
    assert make_thread_open_callback_data(ws_id, thread_id) == (
        f"{THREAD_OPEN_V2_PREFIX}:"
        f"{make_thread_open_token(ws_id)}:"
        f"{make_thread_open_token(thread_id)}"
    )


def test_get_workspace_callback_identity_prefers_daemon_then_storage_key():
    ws = WorkspaceInfo(
        name="sample-workspace",
        path="/Users/example/Projects/sample-workspace",
        tool="codex",
        daemon_workspace_id="codex:sample-workspace",
    )
    assert get_workspace_callback_identity("storage-key", ws) == "codex:sample-workspace"

    ws.daemon_workspace_id = None
    assert get_workspace_callback_identity("storage-key", ws) == "storage-key"
    assert get_workspace_callback_identity("", ws) == "codex:sample-workspace"


def test_normalize_history_turn_timestamp_handles_numeric_and_iso_values():
    assert normalize_history_turn_timestamp(123.9) == 123
    assert normalize_history_turn_timestamp(" 456 ") == 456
    assert normalize_history_turn_timestamp("1970-01-01T00:00:01Z") == 1000
    assert normalize_history_turn_timestamp("not-a-date") == "not-a-date"
    assert normalize_history_turn_timestamp(None) == 0


def test_history_turn_signature_normalizes_timestamp_and_text():
    left = {"role": "user", "timestamp": 1000, "text": " hello "}
    right = {"role": "user", "timestamp": "1000", "text": "hello"}

    assert history_turn_signature(left) == history_turn_signature(right)
    assert history_turn_signature(left) != history_turn_signature({**right, "text": "other"})


def test_format_history_turn_message_filters_empty_and_truncates_assistant_text():
    assert format_history_turn_message({"role": "user", "text": " hello "}) == "👤 hello"
    assert format_history_turn_message({"role": "system", "text": "ignored"}) is None
    assert format_history_turn_message({"role": "assistant", "text": ""}) is None

    msg = format_history_turn_message({"role": "assistant", "text": "a" * 3001})
    assert msg == f"🤖 {'a' * 3000}\n…（截断）"


def test_build_history_sync_batches_splits_without_dropping_header():
    assert build_history_sync_batches(" Header ", ["", "body"]) == ["Header\n\nbody"]
    assert build_history_sync_batches("Header", ["a" * 8, "b" * 8], max_chars=16) == [
        "Header\n\naaaaaaaa",
        "bbbbbbbb",
    ]
