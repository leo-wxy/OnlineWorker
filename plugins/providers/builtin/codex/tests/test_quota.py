from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from plugins.providers.builtin.codex.python.compat import parse_cockpit_tools
from plugins.providers.builtin.codex.python.quota import QuotaError, USAGE_ENDPOINT, fetch_quota, parse_quota, refresh_oauth_record


class Response:
    status = 200

    def __init__(self, value):
        self.raw = json.dumps(value).encode()

    def read(self, _size):
        return self.raw


def record():
    return parse_cockpit_tools({
        "id_token": "id-token",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "account_id": "acct-quota",
        "last_refresh": "2026-08-18T00:00:00Z",
        "email": "quota@example.com",
        "type": "codex",
        "expired": "",
    }).records[0]


def test_fetch_quota_uses_official_endpoint_and_maps_remaining_percent():
    captured = {}

    def opener(request, timeout):
        captured.update(url=request.full_url, headers=dict(request.header_items()), timeout=timeout)
        return Response({
            "plan_type": "pro",
            "rate_limit": {
                "primary_window": {"used_percent": 42, "limit_window_seconds": 18000, "reset_at": 1787000000},
                "secondary_window": {"used_percent": 5, "limit_window_seconds": 604800, "reset_after_seconds": 60},
            },
        })

    value = fetch_quota(record(), opener=opener, now=datetime(2026, 8, 18, tzinfo=UTC))

    assert captured["url"] == USAGE_ENDPOINT
    assert captured["timeout"] == 20
    assert captured["headers"]["Authorization"] == "Bearer access-token"
    assert captured["headers"]["Chatgpt-account-id"] == "acct-quota"
    assert value["planType"] == "pro"
    assert value["primary"]["remainingPercent"] == 58
    assert value["secondary"]["remainingPercent"] == 95


def test_invalid_quota_percent_is_rejected():
    with pytest.raises(QuotaError, match="invalid_quota_response"):
        parse_quota({"rate_limit": {"primary_window": {"used_percent": 101}}})


def test_refresh_preserves_account_identity():
    refreshed = refresh_oauth_record(
        record(),
        opener=lambda request, timeout: Response({"access_token": "new-access", "refresh_token": "new-refresh"}),
        now=datetime(2026, 8, 18, tzinfo=UTC),
    )

    assert refreshed.identity_key == record().identity_key
    assert refreshed.credentials["access_token"] == "new-access"
    assert refreshed.credentials["refresh_token"] == "new-refresh"
