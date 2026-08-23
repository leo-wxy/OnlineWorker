from __future__ import annotations

import base64
import json
import threading
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
    redirect = "http://localhost:1455/auth/callback"
    started = start_oauth(account_store_root, redirect)
    parsed = urlparse(started["authorizationUrl"])
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZE_ENDPOINT
    assert query["client_id"] == [CLIENT_ID]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [redirect]
    assert started["operationId"] == query["state"][0]

    callback = f"{redirect}?code=code-fixture&state={query['state'][0]}"
    raw = complete_oauth(account_store_root, callback, opener=lambda request, timeout: _Response())
    assert raw["account_id"] == "acct-oauth"

    monkeypatch.setattr("plugins.providers.builtin.codex.python.account_feature.complete_oauth", lambda *_args, **_kwargs: raw)
    context = {"data_root": str(account_store_root), "native_paths": []}
    result = handle_account_feature(action="oauth.complete", payload={"callbackUrl": callback}, context=context)
    assert result["ok"] is True
    assert len(AccountStore(account_store_root).list_redacted()) == 1
    assert not (tmp_path / "auth.json").exists()
    assert TOKEN_ENDPOINT == "https://auth.openai.com/oauth/token"


def test_state_mismatch_fails_without_exchange_or_import(account_store_root, monkeypatch):
    redirect = "http://localhost:1455/auth/callback"
    start_oauth(account_store_root, redirect)
    exchanged = False

    def fail_exchange(*_args, **_kwargs):
        nonlocal exchanged
        exchanged = True
        raise AssertionError("state mismatch must not exchange tokens")

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.account_feature.complete_oauth",
        lambda root, callback_url: complete_oauth(root, callback_url, opener=fail_exchange),
    )
    result = handle_account_feature(
        action="oauth.complete",
        payload={"callbackUrl": f"{redirect}?code=x&state=wrong"},
        context={"data_root": str(account_store_root), "native_paths": []},
    )
    assert result["ok"] is False
    assert result["error"] == {"code": "state_mismatch", "message": "OAuth 回调校验失败。"}
    assert exchanged is False
    assert AccountStore(account_store_root).list_redacted() == []


def test_forbidden_endpoint_injection_is_rejected(account_store_root):
    result = handle_account_feature(
        action="oauth.complete",
        payload={"callbackUrl": "http://localhost:1455/auth/callback", "tokenEndpoint": "http://127.0.0.1"},
        context={"data_root": str(account_store_root), "native_paths": []},
    )
    assert result["error"]["code"] == "invalid_request"


def test_denied_callback_cancels_without_exchange_or_import(account_store_root):
    redirect = "http://localhost:1455/auth/callback"
    started = start_oauth(account_store_root, redirect)
    result = handle_account_feature(
        action="oauth.complete",
        payload={"callbackUrl": f"{redirect}?error=access_denied&state={started['operationId']}"},
        context={"data_root": str(account_store_root), "native_paths": []},
    )

    assert result["error"] == {"code": "oauth_cancelled", "message": "OAuth 授权已取消。"}
    assert AccountStore(account_store_root).list_redacted() == []
    assert not (account_store_root / "oauth-pending.json").exists()


def test_cancel_during_exchange_prevents_account_commit(account_store_root, monkeypatch):
    redirect = "http://localhost:1455/auth/callback"
    started = start_oauth(account_store_root, redirect)
    state = started["operationId"]
    callback = f"{redirect}?code=code-fixture&state={state}"
    exchange_started = threading.Event()
    release_exchange = threading.Event()
    completed: list[dict[str, object]] = []

    def blocked_complete(root, callback_url):
        def opener(_request, timeout):
            assert timeout == 20
            exchange_started.set()
            assert release_exchange.wait(timeout=2)
            return _Response()

        return complete_oauth(root, callback_url, opener=opener)

    monkeypatch.setattr("plugins.providers.builtin.codex.python.account_feature.complete_oauth", blocked_complete)
    context = {"data_root": str(account_store_root), "native_paths": []}
    worker = threading.Thread(
        target=lambda: completed.append(
            handle_account_feature(action="oauth.complete", payload={"callbackUrl": callback}, context=context)
        )
    )
    worker.start()
    assert exchange_started.wait(timeout=1)

    cancelled = handle_account_feature(
        action="oauth.cancel",
        payload={"operationId": state},
        context=context,
    )
    release_exchange.set()
    worker.join(timeout=2)

    assert cancelled == {"ok": True, "cancelled": True}
    assert not worker.is_alive()
    assert completed[0]["error"]["code"] == "oauth_not_pending"
    assert AccountStore(account_store_root).list_redacted() == []


def test_stale_cancel_does_not_remove_new_oauth(account_store_root):
    redirect = "http://localhost:1455/auth/callback"
    first = start_oauth(account_store_root, redirect)
    second = start_oauth(account_store_root, redirect)
    context = {"data_root": str(account_store_root), "native_paths": []}

    cancelled = handle_account_feature(
        action="oauth.cancel",
        payload={"operationId": first["operationId"]},
        context=context,
    )
    callback = f"{redirect}?code=code-fixture&state={second['operationId']}"
    stale_error = handle_account_feature(
        action="oauth.complete",
        payload={"callbackUrl": f"{redirect}?error=access_denied&state={first['operationId']}"},
        context=context,
    )

    assert cancelled == {"ok": True, "cancelled": False}
    assert stale_error["error"]["code"] == "state_mismatch"
    assert complete_oauth(account_store_root, callback, opener=lambda _request, timeout: _Response())["account_id"] == "acct-oauth"


def test_oauth_rejects_unregistered_loopback_port(account_store_root):
    with pytest.raises(OAuthError, match="invalid_redirect"):
        start_oauth(account_store_root, "http://127.0.0.1:45678/auth/callback")
