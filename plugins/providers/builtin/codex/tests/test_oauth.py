from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest

from plugins.providers.builtin.codex.python.account_feature import handle_account_feature
from plugins.providers.builtin.codex.python.account_store import AccountStore
from plugins.providers.builtin.codex.python.oauth import AUTHORIZE_ENDPOINT, CLIENT_ID, TOKEN_ENDPOINT, OAuthError, complete_oauth, start_oauth


def _jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"header.{encoded}.signature"


class _Response:
    status = 200

    def read(self, _limit):
        return json.dumps(
            {
                "id_token": _jwt({"email": "oauth@example.com", "https://api.openai.com/auth": {"chatgpt_account_id": "acct-oauth"}}),
                "access_token": _jwt({"exp": 2_000_000_000}),
                "refresh_token": "refresh-fixture",
            }
        ).encode()


def test_pkce_callback_exchange_imports_without_applying(account_store_root, monkeypatch, tmp_path):
    redirect = "http://127.0.0.1:1455/auth/callback"
    started = start_oauth(account_store_root, redirect, now=100)
    parsed = urlparse(started["authorizationUrl"])
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZE_ENDPOINT
    assert query["client_id"] == [CLIENT_ID]
    assert query["code_challenge_method"] == ["S256"]

    callback = f"{redirect}?code=code-fixture&state={query['state'][0]}"
    raw = complete_oauth(account_store_root, callback, opener=lambda request, timeout: _Response(), now=101)
    assert raw["account_id"] == "acct-oauth"

    monkeypatch.setattr("plugins.providers.builtin.codex.python.account_feature.complete_oauth", lambda *_args, **_kwargs: raw)
    context = {"data_root": str(account_store_root), "native_paths": []}
    result = handle_account_feature(action="oauth.complete", payload={"callbackUrl": callback}, context=context)
    assert result["ok"] is True
    assert len(AccountStore(account_store_root).list_redacted()) == 1
    assert not (tmp_path / "auth.json").exists()
    assert TOKEN_ENDPOINT == "https://auth.openai.com/oauth/token"


def test_state_mismatch_and_injection_fail_without_import(account_store_root):
    redirect = "http://127.0.0.1:1455/auth/callback"
    start_oauth(account_store_root, redirect)
    result = handle_account_feature(
        action="oauth.complete",
        payload={"callbackUrl": f"{redirect}?code=x&state=wrong", "tokenEndpoint": "http://127.0.0.1"},
        context={"data_root": str(account_store_root), "native_paths": []},
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_request"
    assert AccountStore(account_store_root).list_redacted() == []


def test_oauth_rejects_unregistered_loopback_port(account_store_root):
    with pytest.raises(OAuthError, match="invalid_redirect"):
        start_oauth(account_store_root, "http://127.0.0.1:45678/auth/callback")
