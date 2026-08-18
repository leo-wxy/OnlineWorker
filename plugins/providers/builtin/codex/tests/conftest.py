from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def account_store_root(tmp_path: Path) -> Path:
    root = tmp_path / "plugin-data" / "accounts"
    assert str(root).startswith(str(tmp_path))
    return root
