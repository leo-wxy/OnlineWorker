from pathlib import Path

import yaml


def _builtin_manifest(provider_id: str) -> dict:
    path = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "providers"
        / "builtin"
        / provider_id
        / "plugin.yaml"
    )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _capability_dict(capabilities) -> dict:
    return {
        "sessions": capabilities.sessions,
        "send": capabilities.send,
        "approvals": capabilities.approvals,
        "questions": capabilities.questions,
        "photos": capabilities.photos,
        "files": capabilities.files,
        "usage": capabilities.usage,
        "commands": capabilities.commands,
        "launch_methods": capabilities.launch_methods,
        "command_wrappers": list(capabilities.command_wrappers),
        "control_modes": list(capabilities.control_modes),
        "message_rewrite": dict(capabilities.message_rewrite),
    }


def test_core_provider_manifest_parser_normalizes_all_capability_fields():
    from core.providers.manifest import metadata_from_provider_manifest

    metadata = metadata_from_provider_manifest(
        {
            "id": "demo",
            "kind": "provider",
            "label": "Demo",
            "description": "Demo provider",
            "default_visible": False,
            "provider": {
                "managed": True,
                "autostart": False,
                "runtime_id": "demo-runtime",
                "bin": "demo-cli",
                "owner_transport": "stdio",
                "live_transport": "owner_bridge",
                "transport": {
                    "type": "stdio",
                    "app_server_port": 1234,
                    "app_server_url": "ws://127.0.0.1:1234",
                },
                "capabilities": {
                    "sessions": True,
                    "send": True,
                    "approvals": True,
                    "questions": True,
                    "photos": True,
                    "files": True,
                    "usage": True,
                    "commands": True,
                    "launch_methods": True,
                    "command_wrappers": ["model", "review"],
                    "control_modes": ["app", "tui"],
                    "message_rewrite": {
                        "app_send": True,
                        "telegram": True,
                        "external_cli": "remote_proxy",
                        "wrapper": "ow-demo",
                    },
                },
                "process": {
                    "cleanup_matchers": ["demo.*server"],
                },
                "health": {
                    "url": "http://127.0.0.1:1234/health",
                },
            },
        }
    )

    assert metadata.id == "demo"
    assert metadata.runtime_id == "demo-runtime"
    assert metadata.label == "Demo"
    assert metadata.description == "Demo provider"
    assert metadata.visible is False
    assert metadata.managed is True
    assert metadata.autostart is False
    assert metadata.bin == "demo-cli"
    assert metadata.transport.owner == "stdio"
    assert metadata.transport.live == "owner_bridge"
    assert metadata.transport.type == "stdio"
    assert metadata.transport.app_server_port == 1234
    assert metadata.transport.app_server_url == "ws://127.0.0.1:1234"
    assert _capability_dict(metadata.capabilities) == {
        "sessions": True,
        "send": True,
        "approvals": True,
        "questions": True,
        "photos": True,
        "files": True,
        "usage": True,
        "commands": True,
        "launch_methods": True,
        "command_wrappers": ["model", "review"],
        "control_modes": ["app", "tui"],
        "message_rewrite": {
            "app_send": True,
            "telegram": True,
            "external_cli": "remote_proxy",
            "wrapper": "ow-demo",
        },
    }
    assert metadata.process.cleanup_matchers == ("demo.*server",)
    assert metadata.health.url == "http://127.0.0.1:1234/health"


def test_builtin_provider_descriptor_capabilities_match_plugin_manifests():
    from core.providers.registry import get_provider

    for provider_id in ("codex", "claude"):
        descriptor = get_provider(provider_id)
        assert descriptor is not None
        assert descriptor.metadata is not None
        manifest = _builtin_manifest(provider_id)
        expected = manifest["provider"]["capabilities"]

        assert _capability_dict(descriptor.metadata.capabilities) == {
            "sessions": bool(expected.get("sessions", False)),
            "send": bool(expected.get("send", False)),
            "approvals": bool(expected.get("approvals", False)),
            "questions": bool(expected.get("questions", False)),
            "photos": bool(expected.get("photos", False)),
            "files": bool(expected.get("files", False)),
            "usage": bool(expected.get("usage", False)),
            "commands": bool(expected.get("commands", False)),
            "launch_methods": bool(expected.get("launch_methods", False)),
            "command_wrappers": list(expected.get("command_wrappers") or []),
            "control_modes": list(expected.get("control_modes") or ["app"]),
            "message_rewrite": dict(expected.get("message_rewrite") or {}),
        }
        assert list(descriptor.capabilities.command_wrappers) == list(
            expected.get("command_wrappers") or []
        )
        assert list(descriptor.capabilities.control_modes) == list(
            expected.get("control_modes") or ["app"]
        )
        if descriptor.message_hooks is not None:
            assert descriptor.message_hooks.supports_photo is bool(expected.get("photos", False))
            assert descriptor.message_hooks.supports_files is bool(expected.get("files", False))
        if bool(expected.get("usage", False)):
            assert descriptor.usage_hooks is not None
            assert callable(descriptor.usage_hooks.get_summary)
        if descriptor.interactions is not None:
            assert bool(descriptor.interactions.build_approval_reply) is bool(
                expected.get("approvals", False)
            )
            assert bool(descriptor.interactions.reply_question) is bool(
                expected.get("questions", False)
            )


def test_builtin_providers_do_not_inline_manifest_capability_schema():
    provider_root = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "providers"
        / "builtin"
    )

    for provider_id in ("codex", "claude"):
        source = (
            provider_root / provider_id / "python" / "provider.py"
        ).read_text(encoding="utf-8")
        assert "ProviderManifestCapabilities(" not in source


def test_builtin_provider_config_blueprint_capabilities_match_plugin_manifests():
    from config import _default_provider_blueprint

    for provider_id in ("codex", "claude"):
        manifest = _builtin_manifest(provider_id)
        expected = manifest["provider"]["capabilities"]
        blueprint = _default_provider_blueprint(provider_id)

        assert blueprint["capabilities"] == {
            "sessions": bool(expected.get("sessions", False)),
            "send": bool(expected.get("send", False)),
            "approvals": bool(expected.get("approvals", False)),
            "questions": bool(expected.get("questions", False)),
            "photos": bool(expected.get("photos", False)),
            "files": bool(expected.get("files", False)),
            "usage": bool(expected.get("usage", False)),
            "commands": bool(expected.get("commands", False)),
            "launch_methods": bool(expected.get("launch_methods", False)),
            "command_wrappers": list(expected.get("command_wrappers") or []),
            "control_modes": list(expected.get("control_modes") or ["app"]),
            "message_rewrite": dict(expected.get("message_rewrite") or {}),
        }
