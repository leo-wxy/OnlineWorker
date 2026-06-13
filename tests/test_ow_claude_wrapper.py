from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_build_ow_claude_child_env_routes_to_local_proxy():
    from plugins.providers.builtin.claude.python.cli_wrapper import build_claude_proxy_env

    env = build_claude_proxy_env(
        {"ANTHROPIC_AUTH_TOKEN": "real-token", "PATH": "/bin"},
        "http://127.0.0.1:45678",
    )

    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:45678"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "real-token"
    assert env["PATH"] == "/bin"
    assert env["ONLINEWORKER_CLAUDE_UPSTREAM_BASE_URL"] == ""


def test_build_ow_claude_child_env_adds_dummy_key_when_proxy_base_url_has_no_credentials():
    from plugins.providers.builtin.claude.python.cli_wrapper import build_claude_proxy_env

    env = build_claude_proxy_env({}, "http://127.0.0.1:45678")

    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:45678"
    assert env["ANTHROPIC_API_KEY"] == "dummy"


def test_build_ow_claude_child_env_keeps_original_base_url_as_upstream():
    from plugins.providers.builtin.claude.python.cli_wrapper import build_claude_proxy_env

    env = build_claude_proxy_env(
        {
            "ANTHROPIC_BASE_URL": "https://upstream.example.test/anthropic",
            "ANTHROPIC_AUTH_TOKEN": "real-token",
        },
        "http://127.0.0.1:45678",
    )

    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:45678"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "real-token"
    assert (
        env["ONLINEWORKER_CLAUDE_UPSTREAM_BASE_URL"]
        == "https://upstream.example.test/anthropic"
    )


def test_build_ow_claude_child_env_keeps_configured_auth_token():
    from plugins.providers.builtin.claude.python.cli_wrapper import build_claude_proxy_env

    env = build_claude_proxy_env(
        {"ANTHROPIC_AUTH_TOKEN": "configured-token"},
        "http://127.0.0.1:45678",
    )

    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:45678"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "configured-token"
    assert "ANTHROPIC_API_KEY" not in env


def test_parse_ow_claude_args_forwards_claude_options_without_separator():
    from plugins.providers.builtin.claude.python.cli_wrapper import parse_ow_claude_args

    args = parse_ow_claude_args(["-p", "你妈的 只回复 OK"])

    assert args.data_dir is None
    assert args.claude_bin == "claude"
    assert args.upstream_base_url is None
    assert args.rewrite is True
    assert args.claude_args == ["-p", "你妈的 只回复 OK"]


def test_ow_claude_script_help_does_not_import_runtime_dependencies():
    result = subprocess.run(
        [str(ROOT / "scripts" / "ow-claude"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Run Claude CLI through OnlineWorker" in result.stdout


def test_parse_ow_claude_args_accepts_wrapper_options_before_claude_options():
    from plugins.providers.builtin.claude.python.cli_wrapper import parse_ow_claude_args

    args = parse_ow_claude_args(
        [
            "--data-dir",
            "/tmp/ow-data",
            "--claude-bin",
            "company-launcher claude",
            "--upstream-base-url",
            "https://api.anthropic.com",
            "--launcher-wraps-claude",
            "--rewrite",
            "--",
            "-p",
            "hello",
        ]
    )

    assert args.data_dir == "/tmp/ow-data"
    assert args.claude_bin == "company-launcher claude"
    assert args.upstream_base_url == "https://api.anthropic.com"
    assert args.launcher_wraps_claude is True
    assert args.rewrite is True
    assert args.claude_args == ["-p", "hello"]


@pytest.mark.asyncio
async def test_run_ow_claude_once_starts_proxy_then_runs_claude(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python import cli_wrapper

    events: list[tuple] = []

    class FakeProxy:
        def __init__(
            self,
            *,
            state,
            upstream_base_url,
            listen_host,
            listen_port,
            rewrite,
            probe,
        ):
            events.append(
                (
                    "init_proxy",
                    upstream_base_url,
                    listen_host,
                    listen_port,
                    rewrite,
                    probe,
                    state.config.providers["claude"].message_hooks,
                )
            )
            self.listen_url = ""

        async def start(self):
            events.append(("start_proxy",))
            self.listen_url = "http://127.0.0.1:45678"
            return self.listen_url

        async def stop(self):
            events.append(("stop_proxy",))

    async def fake_child(argv, env):
        events.append(("child", argv, env["ANTHROPIC_BASE_URL"]))
        return 19

    config = SimpleNamespace(
        providers={
            "claude": SimpleNamespace(
                codex_bin="configured-claude",
                message_hooks=SimpleNamespace(enabled=True),
            )
        },
        get_provider=lambda name: config.providers.get(name),
    )

    monkeypatch.setattr(cli_wrapper, "ClaudeHttpProxy", FakeProxy)
    monkeypatch.setattr(cli_wrapper, "load_config", lambda data_dir=None: config)
    monkeypatch.setattr(cli_wrapper, "set_data_dir", lambda path: events.append(("data_dir", path)))
    monkeypatch.setattr(cli_wrapper, "run_claude_child", fake_child)

    exit_code = await cli_wrapper.run_ow_claude_once(
        ["-p", "hello"],
        data_dir=str(tmp_path),
        upstream_base_url="https://api.example.test",
        claude_bin="configured-claude",
        rewrite=True,
    )

    assert exit_code == 19
    assert events == [
        ("data_dir", str(tmp_path)),
        (
            "init_proxy",
            "https://api.example.test",
            "127.0.0.1",
            0,
            True,
            False,
            config.providers["claude"].message_hooks,
        ),
        ("start_proxy",),
        ("child", ["configured-claude", "-p", "hello"], "http://127.0.0.1:45678"),
        ("stop_proxy",),
    ]


@pytest.mark.asyncio
async def test_run_ow_claude_once_uses_configured_auth_token_when_process_env_missing(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python import cli_wrapper

    observed_env = {}
    observed_proxy = []

    class FakeProxy:
        def __init__(
            self,
            *,
            state,
            upstream_base_url,
            listen_host,
            listen_port,
            rewrite,
            probe,
        ):
            self.listen_url = ""
            observed_proxy.append(upstream_base_url)

        async def start(self):
            self.listen_url = "http://127.0.0.1:45678"
            return self.listen_url

        async def stop(self):
            return None

    async def fake_child(argv, env):
        observed_env.update(env)
        return 0

    config = SimpleNamespace(
        providers={
            "claude": SimpleNamespace(
                codex_bin="configured-claude",
                external_cli={
                    "auth_token": "configured-token",
                    "upstream_base_url": "https://gateway.example.test/anthropic",
                    "model": "deepseek-v4-pro[1m]",
                },
            )
        },
        get_provider=lambda name: config.providers.get(name),
    )

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(cli_wrapper, "ClaudeHttpProxy", FakeProxy)
    monkeypatch.setattr(cli_wrapper, "load_config", lambda data_dir=None: config)
    monkeypatch.setattr(cli_wrapper, "set_data_dir", lambda path: None)
    monkeypatch.setattr(cli_wrapper, "run_claude_child", fake_child)

    exit_code = await cli_wrapper.run_ow_claude_once(
        ["-p", "hello"],
        data_dir=str(tmp_path),
        claude_bin="configured-claude",
        rewrite=True,
    )

    assert exit_code == 0
    assert observed_env["ANTHROPIC_AUTH_TOKEN"] == "configured-token"
    assert observed_env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:45678"
    assert observed_env["ANTHROPIC_MODEL"] == "deepseek-v4-pro[1m]"
    assert observed_env["ONLINEWORKER_CLAUDE_UPSTREAM_BASE_URL"] == "https://gateway.example.test/anthropic"
    assert observed_proxy == ["https://gateway.example.test/anthropic"]
    assert "ANTHROPIC_API_KEY" not in observed_env


@pytest.mark.asyncio
async def test_run_ow_claude_once_can_disable_rewrite_for_probe(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python import cli_wrapper

    observed: list[bool] = []

    class FakeProxy:
        def __init__(
            self,
            *,
            state,
            upstream_base_url,
            listen_host,
            listen_port,
            rewrite,
            probe,
        ):
            observed.append(rewrite)

        async def start(self):
            return "http://127.0.0.1:45678"

        async def stop(self):
            return None

    async def fake_child(argv, env):
        return 0

    config = SimpleNamespace(
        providers={"claude": SimpleNamespace(codex_bin="claude")},
        get_provider=lambda name: config.providers.get(name),
    )

    monkeypatch.setattr(cli_wrapper, "ClaudeHttpProxy", FakeProxy)
    monkeypatch.setattr(cli_wrapper, "load_config", lambda data_dir=None: config)
    monkeypatch.setattr(cli_wrapper, "set_data_dir", lambda path: None)
    monkeypatch.setattr(cli_wrapper, "run_claude_child", fake_child)

    await cli_wrapper.run_ow_claude_once(
        ["-p", "hello"],
        data_dir=str(tmp_path),
        rewrite=False,
        probe=True,
    )

    assert observed == [False]


@pytest.mark.asyncio
async def test_run_ow_claude_once_wraps_external_launcher_with_claude_path_shim(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python import cli_wrapper

    real_bin_dir = tmp_path / "real-bin"
    real_bin_dir.mkdir()
    real_claude = real_bin_dir / "claude"
    real_claude.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    real_claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(real_bin_dir))

    events: list[tuple] = []

    class FakeProxy:
        def __init__(
            self,
            *,
            state,
            upstream_base_url,
            listen_host,
            listen_port,
            rewrite,
            probe,
        ):
            events.append(("init_proxy", upstream_base_url))

        async def start(self):
            return "http://127.0.0.1:45678"

        async def stop(self):
            events.append(("stop_proxy",))

    async def fake_child(argv, env):
        shim_dir = env["PATH"].split(os.pathsep)[0]
        shim_path = Path(shim_dir) / "claude"
        events.append(
            (
                "child",
                argv,
                shim_path.exists(),
                os.access(shim_path, os.X_OK),
                shim_path.read_text(encoding="utf-8"),
            )
        )
        return 0

    config = SimpleNamespace(
        providers={"claude": SimpleNamespace(codex_bin="company-launcher start")},
        get_provider=lambda name: config.providers.get(name),
    )

    monkeypatch.setattr(cli_wrapper, "ClaudeHttpProxy", FakeProxy)
    monkeypatch.setattr(cli_wrapper, "load_config", lambda data_dir=None: config)
    monkeypatch.setattr(cli_wrapper, "set_data_dir", lambda path: None)
    monkeypatch.setattr(cli_wrapper, "run_claude_child", fake_child)

    await cli_wrapper.run_ow_claude_once(
        ["-p", "hello"],
        data_dir=str(tmp_path),
        upstream_base_url="https://upstream.example.test/anthropic",
        launcher_wraps_claude=True,
        rewrite=False,
        probe=True,
    )

    assert events[0] == ("init_proxy", "https://upstream.example.test/anthropic")
    child_event = events[1]
    assert child_event[0] == "child"
    assert child_event[1] == ["company-launcher", "start", "-p", "hello"]
    assert child_event[2] is True
    assert child_event[3] is True
    assert "ANTHROPIC_BASE_URL='http://127.0.0.1:45678'" in child_event[4]
    assert "ONLINEWORKER_CLAUDE_UPSTREAM_BASE_URL='https://upstream.example.test/anthropic'" in child_event[4]
    assert f"exec '{real_claude}' \"$@\"" in child_event[4]
    assert events[2] == ("stop_proxy",)


@pytest.mark.asyncio
async def test_run_ow_claude_once_uses_configured_upstream_base_url(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python import cli_wrapper

    real_bin_dir = tmp_path / "real-bin"
    real_bin_dir.mkdir()
    real_claude = real_bin_dir / "claude"
    real_claude.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    real_claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(real_bin_dir))

    events: list[tuple] = []

    class FakeProxy:
        def __init__(
            self,
            *,
            state,
            upstream_base_url,
            listen_host,
            listen_port,
            rewrite,
            probe,
        ):
            events.append(("init_proxy", upstream_base_url, rewrite, probe))

        async def start(self):
            return "http://127.0.0.1:45678"

        async def stop(self):
            events.append(("stop_proxy",))

    async def fake_child(argv, env):
        shim_path = Path(env["PATH"].split(os.pathsep)[0]) / "claude"
        events.append(("child", argv, shim_path.read_text(encoding="utf-8")))
        return 0

    config = SimpleNamespace(
        providers={
            "claude": SimpleNamespace(
                codex_bin="company-launcher start",
                external_cli={
                    "upstream_base_url": "https://config.example.test/anthropic",
                    "launcher_wraps_claude": True,
                },
            )
        },
        get_provider=lambda name: config.providers.get(name),
    )

    monkeypatch.setattr(cli_wrapper, "ClaudeHttpProxy", FakeProxy)
    monkeypatch.setattr(cli_wrapper, "load_config", lambda data_dir=None: config)
    monkeypatch.setattr(cli_wrapper, "set_data_dir", lambda path: None)
    monkeypatch.setattr(cli_wrapper, "run_claude_child", fake_child)

    await cli_wrapper.run_ow_claude_once(
        ["-p", "hello"],
        data_dir=str(tmp_path),
        rewrite=True,
        probe=True,
    )

    assert events[0] == ("init_proxy", "https://config.example.test/anthropic", True, True)
    child_event = events[1]
    assert child_event[1] == ["company-launcher", "start", "-p", "hello"]
    assert "ONLINEWORKER_CLAUDE_UPSTREAM_BASE_URL='https://config.example.test/anthropic'" in child_event[2]
    assert events[2] == ("stop_proxy",)


def test_ow_claude_script_forwards_original_external_launcher_request_while_message_rewrite_is_sealed(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    captured: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(content_length)
            captured["payload"] = json.loads(body.decode("utf-8"))
            response = json.dumps(
                {"content": [{"type": "text", "text": "UPSTREAM_OK"}]},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format, *args):
            return None

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    upstream_url = f"http://127.0.0.1:{upstream.server_port}"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launcher = bin_dir / "company-launcher"
    launcher.write_text("#!/bin/sh\nexec claude \"$@\"\n", encoding="utf-8")
    launcher.chmod(0o755)
    real_claude = bin_dir / "claude"
    real_claude.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
import urllib.request

prompt = " ".join(sys.argv[1:])
if "-p" in sys.argv:
    index = sys.argv.index("-p")
    if index + 1 < len(sys.argv):
        prompt = sys.argv[index + 1]
base = os.environ["ANTHROPIC_BASE_URL"].rstrip("/")
payload = {
    "model": "test-model",
    "messages": [{"role": "user", "content": prompt}],
}
request = urllib.request.Request(
    base + "/v1/messages",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer fake-token",
        "anthropic-version": "2023-06-01",
    },
    method="POST",
)
with urllib.request.urlopen(request, timeout=10) as response:
    data = json.loads(response.read().decode("utf-8"))
print(data["content"][0]["text"])
""",
        encoding="utf-8",
    )
    real_claude.chmod(0o755)

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
schema_version: 2
providers:
  claude:
    managed: true
    autostart: false
    bin: "company-launcher"
    transport:
      type: stdio
    external_cli:
      launcher_wraps_claude: true
    message_hooks:
      abusive_language_normalization:
        enabled: true
        mode: conservative
logging:
  level: "INFO"
""",
        encoding="utf-8",
    )

    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
        "TELEGRAM_TOKEN": "test:token",
        "ALLOWED_USER_ID": "1",
        "GROUP_CHAT_ID": "-1",
        "ANTHROPIC_BASE_URL": upstream_url,
    }
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "ow-claude"),
                "--data-dir",
                str(tmp_path),
                "--probe",
                "-p",
                "你妈的，只回复 OK",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    finally:
        upstream.shutdown()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "UPSTREAM_OK"
    assert '"event": "rewrite"' not in result.stderr
    assert captured["payload"] == {
        "model": "test-model",
        "messages": [{"role": "user", "content": "你妈的，只回复 OK"}],
    }
