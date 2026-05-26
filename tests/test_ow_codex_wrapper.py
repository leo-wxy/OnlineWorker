from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_build_ow_codex_child_argv_injects_remote_proxy_url():
    from plugins.providers.builtin.codex.python.cli_wrapper import build_codex_remote_argv

    argv = build_codex_remote_argv(
        "codex",
        "ws://127.0.0.1:45678",
        ["-C", "/tmp/project", "你妈的 只回复 OK"],
    )

    assert argv == [
        "codex",
        "--remote",
        "ws://127.0.0.1:45678",
        "-C",
        "/tmp/project",
        "你妈的 只回复 OK",
    ]


def test_build_ow_codex_child_argv_rejects_user_supplied_remote():
    from plugins.providers.builtin.codex.python.cli_wrapper import build_codex_remote_argv

    with pytest.raises(ValueError, match="--remote"):
        build_codex_remote_argv(
            "codex",
            "ws://127.0.0.1:45678",
            ["--remote", "ws://127.0.0.1:1", "hello"],
        )


def test_parse_ow_codex_args_forwards_codex_options_without_separator():
    from plugins.providers.builtin.codex.python.cli_wrapper import parse_ow_codex_args

    args = parse_ow_codex_args(["-C", "/tmp/project", "你妈的 只回复 OK"])

    assert args.data_dir is None
    assert args.codex_args == ["-C", "/tmp/project", "你妈的 只回复 OK"]


def test_parse_ow_codex_args_accepts_wrapper_data_dir_before_codex_options():
    from plugins.providers.builtin.codex.python.cli_wrapper import parse_ow_codex_args

    args = parse_ow_codex_args(
        ["--data-dir", "/tmp/ow-data", "-C", "/tmp/project", "hello"]
    )

    assert args.data_dir == "/tmp/ow-data"
    assert args.codex_args == ["-C", "/tmp/project", "hello"]


def test_parse_ow_codex_args_strips_separator_before_forwarding_to_codex():
    from plugins.providers.builtin.codex.python.cli_wrapper import parse_ow_codex_args

    args = parse_ow_codex_args(["--", "--help"])

    assert args.codex_args == ["--help"]


def test_ow_codex_script_help_does_not_import_runtime_dependencies():
    result = subprocess.run(
        [str(ROOT / "scripts" / "ow-codex"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Run Codex CLI through OnlineWorker" in result.stdout


@pytest.mark.asyncio
async def test_run_ow_codex_once_starts_proxy_then_runs_codex(monkeypatch, tmp_path):
    from plugins.providers.builtin.codex.python import cli_wrapper

    events: list[tuple] = []

    class FakeAppServer:
        def __init__(self, *, codex_bin: str, port: int, protocol: str):
            events.append(("init_server", codex_bin, port, protocol))
            self.stopped = False

        async def start(self):
            events.append(("start_server",))
            return "ws://127.0.0.1:23456"

        async def stop(self):
            events.append(("stop_server",))
            self.stopped = True

    async def fake_proxy(state, upstream_url: str):
        events.append(("proxy", upstream_url, state.config.providers["codex"].message_hooks))
        return "ws://127.0.0.1:34567"

    async def fake_child(argv):
        events.append(("child", argv))
        return 17

    config = SimpleNamespace(
        providers={
            "codex": SimpleNamespace(
                codex_bin="configured-codex",
                app_server_port=0,
                message_hooks=SimpleNamespace(enabled=True),
            )
        },
        get_provider=lambda name: config.providers.get(name),
    )

    monkeypatch.setattr(cli_wrapper, "AppServerProcess", FakeAppServer)
    monkeypatch.setattr(cli_wrapper, "ensure_codex_remote_message_proxy", fake_proxy)
    monkeypatch.setattr(cli_wrapper, "load_config", lambda data_dir=None: config)
    monkeypatch.setattr(cli_wrapper, "set_data_dir", lambda path: events.append(("data_dir", path)))
    monkeypatch.setattr(cli_wrapper, "run_codex_child", fake_child)

    exit_code = await cli_wrapper.run_ow_codex_once(
        ["-C", "/tmp/project", "hello"],
        data_dir=str(tmp_path),
    )

    assert exit_code == 17
    assert events == [
        ("data_dir", str(tmp_path)),
        ("init_server", "configured-codex", 0, "ws"),
        ("start_server",),
        ("proxy", "ws://127.0.0.1:23456", config.providers["codex"].message_hooks),
        (
            "child",
            [
                "configured-codex",
                "--remote",
                "ws://127.0.0.1:34567",
                "-C",
                "/tmp/project",
                "hello",
            ],
        ),
        ("stop_server",),
    ]


@pytest.mark.asyncio
async def test_run_ow_codex_once_cleans_up_when_codex_child_fails(monkeypatch, tmp_path):
    from plugins.providers.builtin.codex.python import cli_wrapper

    events: list[str] = []

    class FakeAppServer:
        def __init__(self, *, codex_bin: str, port: int, protocol: str):
            pass

        async def start(self):
            events.append("start_server")
            return "ws://127.0.0.1:23456"

        async def stop(self):
            events.append("stop_server")

    class FakeProxy:
        listen_url = "ws://127.0.0.1:34567"

        async def stop(self):
            events.append("stop_proxy")

    async def fake_proxy(state, upstream_url: str):
        runtime = state.get_provider_runtime("codex")
        runtime.remote_proxy = FakeProxy()
        events.append("proxy")
        return runtime.remote_proxy.listen_url

    async def fake_child(argv):
        events.append("child")
        raise RuntimeError("child failed")

    config = SimpleNamespace(
        providers={
            "codex": SimpleNamespace(
                codex_bin="codex",
                app_server_port=0,
                message_hooks=SimpleNamespace(enabled=True),
            )
        },
        get_provider=lambda name: config.providers.get(name),
    )

    monkeypatch.setattr(cli_wrapper, "AppServerProcess", FakeAppServer)
    monkeypatch.setattr(cli_wrapper, "ensure_codex_remote_message_proxy", fake_proxy)
    monkeypatch.setattr(cli_wrapper, "load_config", lambda data_dir=None: config)
    monkeypatch.setattr(cli_wrapper, "set_data_dir", lambda path: None)
    monkeypatch.setattr(cli_wrapper, "run_codex_child", fake_child)

    with pytest.raises(RuntimeError, match="child failed"):
        await cli_wrapper.run_ow_codex_once(["hello"], data_dir=str(tmp_path))

    assert events == ["start_server", "proxy", "child", "stop_proxy", "stop_server"]
