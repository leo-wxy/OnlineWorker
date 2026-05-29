import subprocess
import sys
from pathlib import Path


def test_user_message_normalizer_script_reports_normalized_text():
    repo_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "test_user_message_normalizer.py"),
            "你妈的，这什么傻逼问题",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    assert "original: 你妈的，这什么傻逼问题" in result.stdout
    assert "normalized: 这是什么问题" in result.stdout
    assert "changed: true" in result.stdout
    assert "- 你妈的 / abuse_prefix / drop" in result.stdout
    assert "- 傻逼 / insult / drop" in result.stdout
