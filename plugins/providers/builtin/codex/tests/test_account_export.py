from __future__ import annotations

import json
import stat

from plugins.providers.builtin.codex.python.account_store import AccountStore
from plugins.providers.builtin.codex.python.apply import export_accounts
from plugins.providers.builtin.codex.python.compat import parse_cockpit_tools


def test_export_is_cockpit_array_complete_and_permission_tight(account_store_root, tmp_path):
    raw = {
        "auth_mode": "apikey",
        "OPENAI_API_KEY": "export-secret",
        "email": "Export Key",
        "future": {"kept": True},
    }
    record = parse_cockpit_tools(raw).records[0]
    store = AccountStore(account_store_root)
    store.upsert(record)
    destination = tmp_path / "codex-accounts.json"

    result = export_accounts(store, [record.identity_key], destination)

    assert json.loads(destination.read_text()) == [raw]
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert result == {"fileName": "codex-accounts.json", "count": 1, "sizeBytes": destination.stat().st_size}
    assert "export-secret" not in json.dumps(result)
