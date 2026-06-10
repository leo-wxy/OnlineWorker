from types import SimpleNamespace

import pytest

from bot.handlers import workspace as workspace_module
from bot.handlers.workspace import (
    _ensure_thread_topic_header,
    _ensure_workspace_topic_header,
    _open_workspace,
    _workspace_button_label,
)
from bot.handlers.workspace_helpers import (
    make_thread_topic_name,
    make_workspace_storage_key,
    make_workspace_topic_name,
    workspace_path_topic_hint,
)
from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo


GROUP_CHAT_ID = -100123456789


class DummyBot:
    def __init__(self) -> None:
        self.topic_names: list[str] = []
        self.next_topic_id = 1000

    async def create_forum_topic(self, *, chat_id: int, name: str):
        self.topic_names.append(name)
        self.next_topic_id += 1
        return SimpleNamespace(message_thread_id=self.next_topic_id)


class HeaderBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.unpinned_topics: list[dict] = []
        self.pinned_messages: list[dict] = []
        self.edited_messages: list[dict] = []
        self.next_message_id = 2000

    async def send_message(self, *, chat_id: int, text: str, message_thread_id=None, **kwargs):
        self.next_message_id += 1
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "message_thread_id": message_thread_id,
                "kwargs": kwargs,
            }
        )
        return SimpleNamespace(message_id=self.next_message_id)

    async def pin_chat_message(self, *, chat_id: int, message_id: int, disable_notification: bool = True):
        self.pinned_messages.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "disable_notification": disable_notification,
            }
        )

    async def unpin_all_forum_topic_messages(self, *, chat_id: int, message_thread_id: int):
        self.unpinned_topics.append(
            {
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
            }
        )

    async def edit_message_text(self, *, chat_id: int, message_id: int, text: str):
        self.edited_messages.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
            }
        )
        return True


def test_workspace_button_label_prefers_path_hint_before_duplicate_name():
    hotpatch_item = {
        "tool": "claude",
        "name": "music_biz_player",
        "path": "/Users/wxy/Projects/hotpatch/music_app/module_source/music_biz_player",
        "thread_count": 1,
    }
    main_item = {
        "tool": "claude",
        "name": "music_biz_player",
        "path": "/Users/wxy/Projects/music_app/module_source/music_biz_player",
        "thread_count": 10,
    }

    assert _workspace_button_label(hotpatch_item, "📂") == "📂 [claude] · hotpatch/music_app · music_biz_player (1)"
    assert _workspace_button_label(main_item, "📂") == "📂 [claude] · music_app/module_source · music_biz_player (10)"
    assert "\n" not in _workspace_button_label(hotpatch_item, "📂")


def test_workspace_topic_names_use_readable_path_hints_without_hashes():
    main_path = "/Users/wxy/Projects/music_app/module_source/music_biz_player"
    hotpatch_path = "/Users/wxy/Projects/hotpatch/music_app/module_source/music_biz_player"

    assert workspace_path_topic_hint(main_path) == "music_app/module_source"
    assert workspace_path_topic_hint(hotpatch_path) == "hotpatch/music_app"

    main_name = make_workspace_topic_name("claude", "music_biz_player", main_path)
    hotpatch_name = make_workspace_topic_name("claude", "music_biz_player", hotpatch_path)
    thread_name = make_thread_topic_name(
        "claude",
        "music_biz_player",
        "继续",
        "ffa8f949-3b2d-42e8-8f11-fc57cd587ea9",
        workspace_path=hotpatch_path,
    )

    assert main_name == "[claude] music_biz_player @ music_app/module_source"
    assert hotpatch_name == "[claude] music_biz_player @ hotpatch/music_app"
    assert thread_name == "[claude/music_biz_player @ hotpatch/music_app] 继续"
    assert "#" not in main_name
    assert "#" not in hotpatch_name
    assert "#" not in thread_name


@pytest.mark.asyncio
async def test_open_workspace_uses_path_based_storage_key_for_duplicate_names(monkeypatch):
    async def fake_send_to_group(*args, **kwargs):
        return None

    monkeypatch.setattr(workspace_module, "_send_to_group", fake_send_to_group)
    monkeypatch.setattr(workspace_module, "list_provider_threads", lambda *args, **kwargs: [])
    monkeypatch.setattr(workspace_module, "query_provider_active_thread_ids", lambda *args, **kwargs: set())
    monkeypatch.setattr(workspace_module, "save_storage", lambda storage: None)

    main_path = "/Users/wxy/Projects/music_app/module_source/music_biz_player"
    hotpatch_path = "/Users/wxy/Projects/hotpatch/music_app/module_source/music_biz_player"
    storage = AppStorage(
        workspaces={
            "claude:music_biz_player": WorkspaceInfo(
                name="music_biz_player",
                path=main_path,
                tool="claude",
                daemon_workspace_id="claude:music_biz_player",
            )
        }
    )
    state = AppState(storage=storage)

    ws = await _open_workspace(
        bot=DummyBot(),
        state=state,
        storage=storage,
        group_chat_id=GROUP_CHAT_ID,
        tool_cfg=SimpleNamespace(name="claude"),
        name="music_biz_player",
        path=hotpatch_path,
    )

    hotpatch_key = make_workspace_storage_key("claude", hotpatch_path, "music_biz_player")
    assert hotpatch_key in storage.workspaces
    assert storage.workspaces[hotpatch_key] is ws
    assert ws.path == hotpatch_path
    assert ws.daemon_workspace_id == hotpatch_key
    assert storage.workspaces["claude:music_biz_player"].path == main_path


@pytest.mark.asyncio
async def test_open_workspace_migrates_matching_legacy_name_key_to_path_key(monkeypatch):
    async def fake_send_to_group(*args, **kwargs):
        return None

    monkeypatch.setattr(workspace_module, "_send_to_group", fake_send_to_group)
    monkeypatch.setattr(workspace_module, "list_provider_threads", lambda *args, **kwargs: [])
    monkeypatch.setattr(workspace_module, "query_provider_active_thread_ids", lambda *args, **kwargs: set())
    monkeypatch.setattr(workspace_module, "save_storage", lambda storage: None)

    path = "/Users/wxy/Projects/hotpatch/music_app/module_source/music_biz_player"
    legacy_ws = WorkspaceInfo(
        name="music_biz_player",
        path=path,
        tool="claude",
        daemon_workspace_id="claude:music_biz_player",
    )
    storage = AppStorage(workspaces={"claude:music_biz_player": legacy_ws})
    state = AppState(storage=storage)

    ws = await _open_workspace(
        bot=DummyBot(),
        state=state,
        storage=storage,
        group_chat_id=GROUP_CHAT_ID,
        tool_cfg=SimpleNamespace(name="claude"),
        name="music_biz_player",
        path=path,
    )

    path_key = make_workspace_storage_key("claude", path, "music_biz_player")
    assert "claude:music_biz_player" not in storage.workspaces
    assert storage.workspaces[path_key] is legacy_ws
    assert ws is legacy_ws
    assert ws.daemon_workspace_id == path_key


@pytest.mark.asyncio
async def test_workspace_topic_header_pins_full_path(monkeypatch):
    monkeypatch.setattr(workspace_module, "save_storage", lambda storage: None)

    bot = HeaderBot()
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="music_biz_player",
        path="/Users/wxy/Projects/hotpatch/music_app/module_source/music_biz_player",
        tool="claude",
        header_message_id=None,
    )

    await _ensure_workspace_topic_header(
        bot=bot,
        group_chat_id=GROUP_CHAT_ID,
        topic_id=11858,
        ws_info=ws,
        storage=storage,
    )

    assert ws.header_message_id == 2001
    assert bot.sent_messages[0]["message_thread_id"] == 11858
    assert bot.sent_messages[0]["text"] == "路径: /Users/wxy/Projects/hotpatch/music_app/module_source/music_biz_player"
    assert bot.unpinned_topics == [
        {
            "chat_id": GROUP_CHAT_ID,
            "message_thread_id": 11858,
        }
    ]
    assert bot.pinned_messages == [
        {
            "chat_id": GROUP_CHAT_ID,
            "message_id": 2001,
            "disable_notification": True,
        }
    ]


@pytest.mark.asyncio
async def test_thread_topic_header_edits_existing_message_with_preview_and_path(monkeypatch):
    monkeypatch.setattr(workspace_module, "save_storage", lambda storage: None)

    bot = HeaderBot()
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="music_biz_player",
        path="/Users/wxy/Projects/hotpatch/music_app/module_source/music_biz_player",
        tool="claude",
    )
    thread = ThreadInfo(
        thread_id="ffa8f949-3b2d-42e8-8f11-fc57cd587ea9",
        preview="继续处理 hotpatch",
        header_message_id=3456,
    )

    await _ensure_thread_topic_header(
        bot=bot,
        group_chat_id=GROUP_CHAT_ID,
        topic_id=22345,
        ws_info=ws,
        thread_info=thread,
        storage=storage,
    )

    assert thread.header_message_id == 3456
    assert bot.sent_messages == []
    assert bot.unpinned_topics == [
        {
            "chat_id": GROUP_CHAT_ID,
            "message_thread_id": 22345,
        }
    ]
    assert bot.pinned_messages == [
        {
            "chat_id": GROUP_CHAT_ID,
            "message_id": 3456,
            "disable_notification": True,
        }
    ]
    assert bot.edited_messages == [
        {
            "chat_id": GROUP_CHAT_ID,
            "message_id": 3456,
            "text": "路径: /Users/wxy/Projects/hotpatch/music_app/module_source/music_biz_player",
        }
    ]
