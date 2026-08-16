import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import core.usage.runtime as usage_runtime
from core.usage.contracts import UsagePluginDescriptor
from core.usage.runtime import clear_usage_cache, get_usage_source_summary
from plugins.usage.builtin.ccusage.python import runtime as ccusage_runtime


def test_ccusage_runtime_normalizes_daily_rows(monkeypatch, tmp_path: Path):
    binary = tmp_path / "ccusage"
    binary.write_text(
        "#!/bin/sh\ncat <<'JSON'\n" + json.dumps({
            "daily": [{
                "date": "2026-07-11", "inputTokens": 10, "outputTokens": 2,
                "cacheCreationTokens": 3, "cacheReadTokens": 7, "totalTokens": 22,
            }]
        }) + "\nJSON\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    monkeypatch.setenv("ONLINEWORKER_CCUSAGE_BIN", str(binary))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    clear_usage_cache()
    result = get_usage_source_summary("ccusage", "codex", "2026-07-11", "2026-07-11")
    assert result["sourceId"] == "codex"
    assert result["days"] == [{
        "date": "2026-07-11", "inputTokens": 10, "outputTokens": 2,
        "cacheCreationTokens": 3, "cacheReadTokens": 7, "totalTokens": 22,
        "totalCostUsd": None,
    }]


def test_ccusage_runtime_reuses_unchanged_builtin_source(monkeypatch, tmp_path: Path):
    binary = tmp_path / "ccusage"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    codex_home = tmp_path / "codex"
    session_file = codex_home / "sessions" / "session.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_text("first\n", encoding="utf-8")
    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        payload = {"daily": [{"date": "2026-07-11", "totalTokens": len(calls)}]}
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    monkeypatch.setenv("ONLINEWORKER_CCUSAGE_BIN", str(binary))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(ccusage_runtime.subprocess, "run", fake_run)
    clear_usage_cache()

    first = get_usage_source_summary(
        "ccusage", "codex", "2026-07-11", "2026-07-11", force_refresh=True,
    )
    second = get_usage_source_summary(
        "ccusage", "codex", "2026-07-11", "2026-07-11", force_refresh=True,
    )

    assert first["days"] == second["days"]
    assert len(calls) == 1

    session_file.write_text("first\nsecond\n", encoding="utf-8")
    refreshed = get_usage_source_summary(
        "ccusage", "codex", "2026-07-11", "2026-07-11", force_refresh=True,
    )

    assert refreshed["days"][0]["totalTokens"] == 2
    assert len(calls) == 2


def test_usage_runtime_coalesces_same_inflight_query(monkeypatch):
    calls = 0
    started = threading.Event()
    release = threading.Event()

    def get_summary(_request):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(2)
        return {"days": [], "updatedAtEpoch": 1}

    descriptor = UsagePluginDescriptor(
        plugin_id="sample",
        runtime_identity=lambda: "sample-runtime",
        get_summary=get_summary,
    )
    monkeypatch.setattr(usage_runtime, "resolve_usage_plugin", lambda *_args: descriptor)
    clear_usage_cache()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            get_usage_source_summary,
            "sample", "sample", "2026-07-11", "2026-07-11",
            force_refresh=True,
        )
        assert started.wait(1)
        second = pool.submit(
            get_usage_source_summary,
            "sample", "sample", "2026-07-11", "2026-07-11",
            force_refresh=True,
        )
        time.sleep(0.05)
        release.set()
        assert first.result(timeout=1) == second.result(timeout=1)

    assert calls == 1
