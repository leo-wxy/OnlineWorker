from __future__ import annotations

from pathlib import Path

from core.account_features import account_feature_backend_module, list_account_features
from plugins.providers.builtin.codex.python import oauth, quota


ROOT = Path(__file__).resolve().parents[5]
CODEX_PYTHON = ROOT / "plugins/providers/builtin/codex/python"


def test_enabled_manifest_entries_and_backend_module_agree() -> None:
    features = list_account_features(overlay_spec="")
    codex = next(feature for feature in features if feature.feature_id == "codex")
    assert codex.frontend_entry == "frontend/account_entry.tsx"
    assert codex.backend_entry == "python/account_feature.py"
    assert account_feature_backend_module("codex") == "plugins.providers.builtin.codex.python.account_feature"


def test_account_modules_stay_independent_and_share_one_lock() -> None:
    sources = {path.name: path.read_text(encoding="utf-8") for path in CODEX_PYTHON.glob("*.py") if path.name in {"account_feature.py", "oauth.py", "quota.py", "apply.py", "session_assets.py", "session_package.py"}}
    combined = "\n".join(sources.values())
    for forbidden in ("provider_owner_bridge", "app_server", "EventBus", "TaskBoard", "get_usage_source_summary", "list_provider_sessions"):
        assert forbidden not in combined
    for name in ("oauth.py", "apply.py", "session_assets.py", "account_feature.py"):
        assert "operation_lock" in sources[name]


def test_oauth_network_identity_is_fixed_and_https() -> None:
    assert oauth.CLIENT_ID == "app_EMoamEEZ73f0CkXaXp7hrann"
    assert oauth.AUTHORIZE_ENDPOINT == "https://auth.openai.com/oauth/authorize"
    assert oauth.TOKEN_ENDPOINT == "https://auth.openai.com/oauth/token"
    assert quota.USAGE_ENDPOINT == "https://chatgpt.com/backend-api/wham/usage"


def test_visibility_scope_has_only_official_state_databases() -> None:
    source = (CODEX_PYTHON / "session_assets.py").read_text(encoding="utf-8")
    assert 'home / "state_5.sqlite"' in source
    assert 'home / "sqlite" / "state_5.sqlite"' in source
    assert "codex-dev.db" not in source
