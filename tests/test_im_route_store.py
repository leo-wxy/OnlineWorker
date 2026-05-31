from __future__ import annotations

import sqlite3

from core.im_routes import ImRouteStore
from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo, save_storage


GROUP_CHAT_ID = -100123456


def _route_store(tmp_path) -> ImRouteStore:
    return ImRouteStore(tmp_path / "im-routes.sqlite3")


def test_migrates_telegram_json_topics_to_generic_im_routes(tmp_path):
    storage = AppStorage(
        global_topic_ids={"codex": 11},
        workspaces={
            "codex:/repo": WorkspaceInfo(
                name="repo",
                path="/repo",
                tool="codex",
                topic_id=22,
                threads={
                    "session-1": ThreadInfo(
                        thread_id="session-1",
                        topic_id=33,
                        preview="hello",
                    )
                },
            )
        },
    )

    store = _route_store(tmp_path)
    store.migrate_telegram_json_topics(storage, GROUP_CHAT_ID)

    rows = store.list_routes()

    assert [
        (row.im_provider, row.im_space_id, row.im_entry_id, row.route_scope, row.agent_provider, row.workspace_id, row.session_id)
        for row in rows
    ] == [
        ("telegram", str(GROUP_CHAT_ID), "11", "agent", "codex", None, None),
        ("telegram", str(GROUP_CHAT_ID), "22", "workspace", "codex", "codex:/repo", None),
        ("telegram", str(GROUP_CHAT_ID), "33", "session", "codex", "codex:/repo", "session-1"),
    ]


def test_sqlite_routes_survive_json_save_and_restore_topic_mirrors(tmp_path):
    storage = AppStorage(
        global_topic_ids={"codex": 11},
        workspaces={
            "codex:/repo": WorkspaceInfo(
                name="repo",
                path="/repo",
                tool="codex",
                topic_id=22,
                threads={"session-1": ThreadInfo(thread_id="session-1", topic_id=33)},
            )
        },
    )
    store = _route_store(tmp_path)
    store.migrate_telegram_json_topics(storage, GROUP_CHAT_ID)

    storage.global_topic_ids.clear()
    storage.workspaces["codex:/repo"].topic_id = None
    storage.workspaces["codex:/repo"].threads["session-1"].topic_id = None
    save_storage(storage, str(tmp_path / "onlineworker_state.json"))

    reloaded = AppStorage(
        global_topic_ids={},
        workspaces={
            "codex:/repo": WorkspaceInfo(
                name="repo",
                path="/repo",
                tool="codex",
                topic_id=None,
                threads={"session-1": ThreadInfo(thread_id="session-1", topic_id=None)},
            )
        },
    )
    store.restore_telegram_topic_mirrors(reloaded, GROUP_CHAT_ID)

    assert reloaded.global_topic_ids == {"codex": 11}
    assert reloaded.workspaces["codex:/repo"].topic_id == 22
    assert reloaded.workspaces["codex:/repo"].threads["session-1"].topic_id == 33


def test_state_topic_lookup_uses_sqlite_when_json_mirror_is_missing(tmp_path):
    storage = AppStorage(
        global_topic_ids={"codex": 11},
        workspaces={
            "codex:/repo": WorkspaceInfo(
                name="repo",
                path="/repo",
                tool="codex",
                topic_id=22,
                threads={"session-1": ThreadInfo(thread_id="session-1", topic_id=33)},
            )
        },
    )
    store = _route_store(tmp_path)
    store.migrate_telegram_json_topics(storage, GROUP_CHAT_ID)

    storage.global_topic_ids.clear()
    storage.workspaces["codex:/repo"].topic_id = None
    storage.workspaces["codex:/repo"].threads["session-1"].topic_id = None

    state = AppState(storage=storage)
    state.set_im_route_store(store, GROUP_CHAT_ID)

    assert state.get_global_topic_id("codex") == 11
    assert state.is_global_topic(11)
    assert state.get_tool_by_global_topic(11) == "codex"
    assert state.find_workspace_by_topic_id(22) is storage.workspaces["codex:/repo"]
    assert state.find_thread_by_topic_id(33) == (
        storage.workspaces["codex:/repo"],
        storage.workspaces["codex:/repo"].threads["session-1"],
    )


def test_unknown_telegram_entry_is_recorded_without_fallback_route(tmp_path):
    storage = AppStorage(
        active_workspace="codex:/repo",
        workspaces={
            "codex:/repo": WorkspaceInfo(
                name="repo",
                path="/repo",
                tool="codex",
                topic_id=22,
            )
        },
    )
    store = _route_store(tmp_path)
    state = AppState(storage=storage)
    state.set_im_route_store(store, GROUP_CHAT_ID)

    state.observe_unknown_telegram_topic(999, display_name="lost topic")

    route = store.get_route("telegram", "default", str(GROUP_CHAT_ID), "999")
    assert route is not None
    assert route.route_scope == "unknown"
    assert route.display_name == "lost topic"
    assert state.find_workspace_by_topic_id(999) is None
    assert state.find_thread_by_topic_id(999) is None


def test_replacing_workspace_topic_keeps_old_route_but_only_new_route_active(tmp_path):
    store = _route_store(tmp_path)

    store.upsert_telegram_workspace_route(
        GROUP_CHAT_ID,
        22,
        agent_provider="codex",
        workspace_id="codex:/repo",
        workspace_path="/repo",
        display_name="repo",
    )
    store.upsert_telegram_workspace_route(
        GROUP_CHAT_ID,
        44,
        agent_provider="codex",
        workspace_id="codex:/repo",
        workspace_path="/repo",
        display_name="repo",
    )

    old_route = store.get_route("telegram", "default", str(GROUP_CHAT_ID), "22")
    new_route = store.get_route("telegram", "default", str(GROUP_CHAT_ID), "44")

    assert old_route is not None
    assert old_route.status == "closed"
    assert new_route is not None
    assert new_route.status == "active"
    assert store.get_telegram_workspace_topic_id(
        GROUP_CHAT_ID,
        agent_provider="codex",
        workspace_id="codex:/repo",
    ) == 44


def test_im_route_store_uses_requested_test_database_only(tmp_path):
    db_path = tmp_path / "im-routes.sqlite3"
    store = ImRouteStore(db_path)
    store.initialize()

    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert names == {"im_routes"}
