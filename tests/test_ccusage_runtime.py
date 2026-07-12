import json
from pathlib import Path

from core.usage.runtime import clear_usage_cache, get_usage_source_summary


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
    clear_usage_cache()
    result = get_usage_source_summary("ccusage", "codex", "2026-07-11", "2026-07-11")
    assert result["sourceId"] == "codex"
    assert result["days"] == [{
        "date": "2026-07-11", "inputTokens": 10, "outputTokens": 2,
        "cacheCreationTokens": 3, "cacheReadTokens": 7, "totalTokens": 22,
        "totalCostUsd": None,
    }]
