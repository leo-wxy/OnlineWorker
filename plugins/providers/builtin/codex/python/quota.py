from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from plugins.providers.builtin.codex.python.account_model import AccountRecord, create_account_record, decode_jwt_payload
from plugins.providers.builtin.codex.python.oauth import CLIENT_ID, TOKEN_ENDPOINT


USAGE_ENDPOINT = "https://chatgpt.com/backend-api/wham/usage"
MAX_RESPONSE_BYTES = 1024 * 1024
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"


class QuotaError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _read_json(response: object, error_code: str) -> dict:
    status = int(getattr(response, "status", 200))
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if status < 200 or status >= 300 or len(raw) > MAX_RESPONSE_BYTES:
        raise QuotaError("unauthorized" if status in {401, 403} else error_code)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QuotaError(error_code) from exc
    if not isinstance(value, dict):
        raise QuotaError(error_code)
    return value


def _window(value: object, now: datetime) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    used = value.get("used_percent")
    if isinstance(used, bool) or not isinstance(used, (int, float)) or not 0 <= used <= 100:
        raise QuotaError("invalid_quota_response")
    reset_at = value.get("reset_at")
    if not isinstance(reset_at, (int, float)):
        after = value.get("reset_after_seconds")
        reset_at = now.timestamp() + after if isinstance(after, (int, float)) and after >= 0 else None
    return {
        "usedPercent": round(float(used), 1),
        "remainingPercent": round(100 - float(used), 1),
        "windowSeconds": int(value["limit_window_seconds"]) if isinstance(value.get("limit_window_seconds"), (int, float)) else None,
        "resetAt": datetime.fromtimestamp(reset_at, UTC).isoformat().replace("+00:00", "Z") if reset_at is not None else None,
    }


def parse_quota(value: object, *, now: datetime | None = None) -> dict[str, object]:
    if not isinstance(value, dict):
        raise QuotaError("invalid_quota_response")
    rate_limit = value.get("rate_limit")
    rate_limit = rate_limit if isinstance(rate_limit, dict) else {}
    timestamp = now or datetime.now(UTC)
    credits = value.get("rate_limit_reset_credits")
    available = credits.get("available_count") if isinstance(credits, dict) else None
    return {
        "status": "ok",
        "planType": value.get("plan_type") if isinstance(value.get("plan_type"), str) else "",
        "primary": _window(rate_limit.get("primary_window"), timestamp),
        "secondary": _window(rate_limit.get("secondary_window"), timestamp),
        "resetCreditsAvailable": int(available) if isinstance(available, (int, float)) else None,
        "refreshedAt": timestamp.isoformat().replace("+00:00", "Z"),
    }


def fetch_quota(record: AccountRecord, *, opener=urlopen, now: datetime | None = None) -> dict[str, object]:
    if record.auth_mode != "token":
        return {"status": "unsupported", "refreshedAt": (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")}
    token = record.credentials.get("access_token")
    if not isinstance(token, str) or not token:
        raise QuotaError("missing_access_token")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": "https://chatgpt.com/",
        "User-Agent": USER_AGENT,
        "OpenAI-Beta": "codex-1",
        "oai-language": "zh-CN",
        "originator": "Codex Desktop",
        "sec-fetch-site": "none",
        "sec-fetch-mode": "no-cors",
        "sec-fetch-dest": "empty",
        "priority": "u=4, i",
    }
    account_id = record.credentials.get("account_id")
    if isinstance(account_id, str) and account_id:
        headers["ChatGPT-Account-Id"] = account_id
    request = Request(USAGE_ENDPOINT, headers=headers, method="GET")
    try:
        return parse_quota(_read_json(opener(request, timeout=20), "quota_request_failed"), now=now)
    except HTTPError as exc:
        raise QuotaError("unauthorized" if exc.code in {401, 403} else "quota_request_failed") from exc
    except QuotaError:
        raise
    except Exception as exc:
        raise QuotaError("quota_request_failed") from exc


def _jwt_expiry(token: object) -> str:
    exp = decode_jwt_payload(token).get("exp")
    return datetime.fromtimestamp(exp, UTC).isoformat().replace("+00:00", "Z") if isinstance(exp, (int, float)) else ""


def refresh_oauth_record(record: AccountRecord, *, opener=urlopen, now: datetime | None = None) -> AccountRecord:
    refresh_token = record.credentials.get("refresh_token")
    if record.auth_mode != "token" or not isinstance(refresh_token, str) or not refresh_token:
        raise QuotaError("token_refresh_unavailable")
    body = urlencode({"grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": refresh_token}).encode()
    request = Request(TOKEN_ENDPOINT, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        value = _read_json(opener(request, timeout=20), "token_refresh_failed")
    except HTTPError as exc:
        raise QuotaError("token_refresh_failed") from exc
    except QuotaError:
        raise
    except Exception as exc:
        raise QuotaError("token_refresh_failed") from exc
    access_token = value.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise QuotaError("token_refresh_failed")
    credentials = deepcopy(record.credentials)
    credentials["access_token"] = access_token
    for key in ("id_token", "refresh_token"):
        if isinstance(value.get(key), str) and value[key]:
            credentials[key] = value[key]
    timestamp = now or datetime.now(UTC)
    credentials["last_refresh"] = timestamp.isoformat().replace("+00:00", "Z")
    credentials["expired"] = _jwt_expiry(access_token)
    return create_account_record(credentials, auth_mode="token", source=record.source)
