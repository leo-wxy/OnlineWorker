import pytest


@pytest.mark.asyncio
async def test_provider_session_bridge_forwards_attachments_to_message_hooks(monkeypatch):
    from core import provider_session_bridge

    captured = {}

    class _FakeAdapter:
        connected = True

    async def _start_adapter(descriptor, provider_id):
        assert provider_id == "overlay-tool"
        return _FakeAdapter()

    async def _send(state, adapter, ws_info, thread_info, **kwargs):
        captured["workspace"] = ws_info["path"]
        captured["thread_id"] = thread_info["thread_id"]
        captured["text"] = kwargs["text"]
        captured["attachments"] = kwargs["attachments"]

    monkeypatch.setattr(
        provider_session_bridge,
        "_load_provider_descriptor",
        lambda provider_id: type(
            "Descriptor",
            (),
            {
                "message_hooks": type(
                    "MessageHooks",
                    (),
                    {
                        "send": _send,
                    },
                )(),
            },
        )(),
    )
    monkeypatch.setattr(provider_session_bridge, "_provider_session_adapter", _start_adapter)
    monkeypatch.setattr(
        provider_session_bridge,
        "list_provider_session_rows",
        lambda provider_id: [{"id": "tid-1", "workspace": "/tmp/project-a"}],
    )

    await provider_session_bridge.send_provider_session_message(
        "overlay-tool",
        "tid-1",
        "hello attachment",
        workspace_dir="/tmp/project-a",
        attachments=[
            {
                "kind": "image",
                "path": "/tmp/project-a/image.png",
                "name": "image.png",
            }
        ],
    )

    assert captured == {
        "workspace": "/tmp/project-a",
        "thread_id": "tid-1",
        "text": "hello attachment",
        "attachments": [
            {
                "kind": "image",
                "path": "/tmp/project-a/image.png",
                "name": "image.png",
            }
        ],
    }
