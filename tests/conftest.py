from __future__ import annotations

import shutil
import tempfile

import pytest


@pytest.fixture(autouse=True)
def isolate_onlineworker_data_dir(tmp_path, monkeypatch, request):
    """Keep tests from reading or writing the real OnlineWorker app data dir."""
    if request.node.get_closest_marker("allow_missing_data_dir"):
        monkeypatch.setattr("config._data_dir", None, raising=False)
        yield
        return

    # Keep this path short enough for AF_UNIX sockets such as
    # provider_owner_bridge.sock on macOS.
    data_dir = tempfile.mkdtemp(prefix="owt-", dir="/tmp")
    monkeypatch.setattr("config._data_dir", str(data_dir), raising=False)
    monkeypatch.setattr("main.default_data_dir", lambda: str(data_dir), raising=False)
    try:
        yield
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
