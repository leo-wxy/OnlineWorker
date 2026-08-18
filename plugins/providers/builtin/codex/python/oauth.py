from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from plugins.providers.builtin.codex.python.account_model import decode_jwt_payload
from plugins.providers.builtin.codex.python.account_store import atomic_write, operation_lock


CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_ENDPOINT = "https://auth.openai.com/oauth/authorize"
TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"
CALLBACK_PATH = "/auth/callback"
PENDING_TTL_SECONDS = 10 * 60
SCOPES = "openid profile email offline_access api.connectors.read api.connectors.invoke"


class OAuthError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _pending_path(root: str | Path) -> Path:
    return Path(root).resolve() / "oauth-pending.json"


def _redirect_uri(value: object) -> str:
    if not isinstance(value, str):
        raise OAuthError("invalid_redirect")
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.path != CALLBACK_PATH
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or parsed.port != 1455
    ):
        raise OAuthError("invalid_redirect")
    return value


def start_oauth(root: str | Path, redirect_uri: object, *, now: float | None = None) -> dict[str, object]:
    redirect = _redirect_uri(redirect_uri)
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    created_at = time.time() if now is None else now
    pending = {"state": state, "verifier": verifier, "redirect_uri": redirect, "created_at": created_at}
    with operation_lock(root):
        atomic_write(_pending_path(root), json.dumps(pending, separators=(",", ":")).encode())
    query = urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect,
            "scope": SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "state": state,
            "originator": "codex_vscode",
        }
    )
    return {
        "authorizationUrl": f"{AUTHORIZE_ENDPOINT}?{query}",
        "expiresAt": int(created_at + PENDING_TTL_SECONDS),
    }


def cancel_oauth(root: str | Path) -> None:
    with operation_lock(root):
        _pending_path(root).unlink(missing_ok=True)


def _read_pending(root: str | Path, now: float) -> dict:
    path = _pending_path(root)
    try:
        pending = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OAuthError("oauth_not_pending") from exc
    if now - float(pending.get("created_at", 0)) > PENDING_TTL_SECONDS:
        path.unlink(missing_ok=True)
        raise OAuthError("oauth_expired")
    return pending


def _account_id(claims: dict, response: dict) -> str:
    auth = claims.get("https://api.openai.com/auth")
    candidates = [
        response.get("account_id"),
        claims.get("chatgpt_account_id"),
        claims.get("account_id"),
        auth.get("chatgpt_account_id") if isinstance(auth, dict) else None,
    ]
    return next((value.strip() for value in candidates if isinstance(value, str) and value.strip()), "")


def _portable_tokens(response: dict) -> dict:
    id_token = response.get("id_token")
    access_token = response.get("access_token")
    refresh_token = response.get("refresh_token")
    if not all(isinstance(value, str) and value for value in (id_token, access_token, refresh_token)):
        raise OAuthError("invalid_token_response")
    claims = decode_jwt_payload(id_token)
    account_id = _account_id(claims, response)
    email = claims.get("email") if isinstance(claims.get("email"), str) else ""
    if not account_id and not email:
        raise OAuthError("missing_identity")
    access_claims = decode_jwt_payload(access_token)
    exp = access_claims.get("exp")
    expired = datetime.fromtimestamp(exp, UTC).isoformat().replace("+00:00", "Z") if isinstance(exp, (int, float)) else ""
    return {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account_id,
        "last_refresh": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "email": email,
        "type": "codex",
        "expired": expired,
    }


def complete_oauth(
    root: str | Path,
    callback_url: object,
    *,
    opener=urlopen,
    now: float | None = None,
) -> dict:
    if not isinstance(callback_url, str):
        raise OAuthError("invalid_callback")
    timestamp = time.time() if now is None else now
    with operation_lock(root):
        pending = _read_pending(root, timestamp)
        parsed = urlparse(callback_url)
        expected = urlparse(pending["redirect_uri"])
        if (parsed.scheme, parsed.netloc, parsed.path) != (expected.scheme, expected.netloc, expected.path):
            raise OAuthError("invalid_callback")
        params = parse_qs(parsed.query, keep_blank_values=True)
        if params.get("error", [""])[0]:
            cancel_oauth(root)
            raise OAuthError("oauth_cancelled")
        code = params.get("code", [""])[0]
        state = params.get("state", [""])[0]
        if not code or not secrets.compare_digest(state, pending["state"]):
            raise OAuthError("state_mismatch")
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "code_verifier": pending["verifier"],
                "redirect_uri": pending["redirect_uri"],
            }
        ).encode()
        request = Request(TOKEN_ENDPOINT, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            response = opener(request, timeout=20)
            status = getattr(response, "status", 200)
            raw = response.read(1024 * 1024 + 1)
            if status < 200 or status >= 300 or len(raw) > 1024 * 1024:
                raise OAuthError("token_exchange_failed")
            value = json.loads(raw)
        except OAuthError:
            raise
        except Exception as exc:
            raise OAuthError("token_exchange_failed") from exc
        if not isinstance(value, dict):
            raise OAuthError("invalid_token_response")
        return _portable_tokens(value)
