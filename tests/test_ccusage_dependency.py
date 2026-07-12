from __future__ import annotations

import configparser
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CCUSAGE_DIR = ROOT / "third_party" / "ccusage"
PRICING_PATH = ROOT / "third_party" / "ccusage-pricing.json"
EXPECTED_TAG = "v20.0.17"
EXPECTED_COMMIT = "88cdfa4fb201c92b163a34d0bbb097b68d3185cf"
EXPECTED_LITELLM_REV = "49ca04d8c3ddea336237ce6f3082dbc26d19e944"
EXPECTED_PRICING_SHA256 = (
    "ae4532ba0c5da03ed694f37fffa050a65e0e250b816dcdb475bee0b7b7b1aa97"
)
EXPECTED_AGENT_IDS = [
    "claude",
    "codex",
    "opencode",
    "amp",
    "droid",
    "codebuff",
    "hermes",
    "pi",
    "goose",
    "openclaw",
    "kilo",
    "copilot",
    "gemini",
    "kimi",
    "qwen",
]


def run_git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_ccusage_submodule_uses_canonical_upstream_url():
    config = configparser.ConfigParser()
    with (ROOT / ".gitmodules").open(encoding="utf-8") as handle:
        config.read_file(handle)

    section = 'submodule "third_party/ccusage"'
    assert config[section]["path"] == "third_party/ccusage"
    assert config[section]["url"] == "https://github.com/ccusage/ccusage.git"


def test_ccusage_gitlink_is_pinned_to_verified_tag_commit():
    mode, commit, _stage_and_path = run_git(
        "ls-files", "--stage", "--", "third_party/ccusage"
    ).split(maxsplit=2)

    assert mode == "160000"
    assert commit == EXPECTED_COMMIT
    assert run_git("rev-parse", "HEAD", cwd=CCUSAGE_DIR) == EXPECTED_COMMIT
    assert (
        run_git("rev-parse", f"refs/tags/{EXPECTED_TAG}^{{commit}}", cwd=CCUSAGE_DIR)
        == EXPECTED_COMMIT
    )


def test_checked_in_pricing_snapshot_matches_ccusage_build_contract():
    flake_lock = json.loads((CCUSAGE_DIR / "flake.lock").read_text(encoding="utf-8"))
    assert flake_lock["nodes"]["litellm"]["locked"]["rev"] == EXPECTED_LITELLM_REV

    pricing_bytes = PRICING_PATH.read_bytes()
    assert hashlib.sha256(pricing_bytes).hexdigest() == EXPECTED_PRICING_SHA256
    pricing = json.loads(pricing_bytes)
    assert isinstance(pricing, dict)
    assert pricing
    assert any(
        model.startswith(("claude-", "gpt-", "openai/"))
        and isinstance(values, dict)
        and "input_cost_per_token" in values
        and "output_cost_per_token" in values
        for model, values in pricing.items()
    )

    build_script = (CCUSAGE_DIR / "rust/crates/ccusage/build.rs").read_text(
        encoding="utf-8"
    )
    assert 'const PRICING_JSON_PATH_ENV: &str = "CCUSAGE_PRICING_JSON_PATH";' in build_script
    assert "env::var_os(PRICING_JSON_PATH_ENV)" in build_script
    assert "fs::read_to_string(path)" in build_script

    env = os.environ.copy()
    env["CCUSAGE_PRICING_JSON_PATH"] = str(PRICING_PATH)
    configured_path = Path(env["CCUSAGE_PRICING_JSON_PATH"])
    assert json.loads(configured_path.read_text(encoding="utf-8")) == pricing


def test_sync_script_extracts_agents_without_usage_manifest(tmp_path: Path):
    loader = tmp_path / "loader.rs"
    loader.write_text(
        """
pub(crate) const BUILT_IN_AGENT_NAMES: &[&str] = &[
    "codex",
    "claude",
];
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "sync-ccusage-sources.py"),
            "--loader",
            str(loader),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == ["codex", "claude"]
    assert not any(tmp_path.rglob("*manifest*"))


def test_sync_script_reports_pinned_ccusage_agent_ids():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync-ccusage-sources.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == EXPECTED_AGENT_IDS
    assert len(result.stdout.splitlines()) == len(set(result.stdout.splitlines()))
