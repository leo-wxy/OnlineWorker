from __future__ import annotations

import json

from plugins.providers.builtin.codex.python.compat import (
    export_cockpit_tools,
    parse_cockpit_tools,
    parse_local_auth,
)


def token_fixture(**updates):
    value = {
        "id_token": "id-token-fixture",
        "access_token": "access-token-fixture",
        "refresh_token": "refresh-token-fixture",
        "account_id": "account-token",
        "last_refresh": "2026-08-17T00:00:00Z",
        "email": "token@example.com",
        "type": "codex",
        "expired": "",
        "future_top_level": {"kept": True},
    }
    value.update(updates)
    return value


def agent_identity_fixture():
    return {
        "auth_mode": "agentIdentity",
        "agent_identity": {
            "agent_runtime_id": "runtime-fixture",
            "agent_private_key": "private-key-fixture",
            "account_id": "account-agent",
            "chatgpt_user_id": "user-agent",
            "future_nested": {"kept": True},
        },
        "account_id": "account-agent",
        "user_id": "user-agent",
        "email": "agent@example.com",
        "type": "codex",
    }


def api_key_fixture():
    return {
        "auth_mode": "apikey",
        "OPENAI_API_KEY": "api-key-fixture",
        "email": "API Key",
        "api_base_url": "https://api.example.invalid/v1",
        "api_provider_id": "fixture",
        "api_provider_name": "Fixture",
    }


def test_object_array_and_local_file_inputs_share_one_parser():
    one = parse_cockpit_tools(json.dumps(token_fixture()), source="oauth")
    many = parse_cockpit_tools(json.dumps([token_fixture(), api_key_fixture()]))
    local = parse_local_auth(json.dumps(token_fixture()))

    assert one.error is None
    assert [item.status for item in one.items] == ["accepted"]
    assert one.records[0].source == "oauth"
    assert [record.auth_mode for record in many.records] == ["token", "apikey"]
    assert local.records[0].source == "local_file"


def test_unsupported_shape_version_and_bad_items_are_explicit_rejections():
    assert parse_cockpit_tools("42").error.code == "unsupported_shape"
    assert parse_cockpit_tools(json.dumps({"version": 2, "accounts": []})).error.code == "unsupported_version"

    result = parse_cockpit_tools(json.dumps([token_fixture(), {"auth_mode": "unknown"}, None]))

    assert [item.status for item in result.items] == ["accepted", "rejected", "rejected"]
    assert [item.error.code for item in result.items[1:]] == ["unsupported_auth_mode", "invalid_item"]


def test_three_cockpit_modes_round_trip_without_losing_unknown_fields():
    fixtures = [token_fixture(), agent_identity_fixture(), api_key_fixture()]
    parsed = parse_cockpit_tools(json.dumps(fixtures))

    assert [record.auth_mode for record in parsed.records] == ["token", "agentIdentity", "apikey"]
    exported = json.loads(export_cockpit_tools(parsed.records))

    assert exported == fixtures
    assert "access_token" not in exported[1]
    assert exported[1]["agent_identity"]["future_nested"] == {"kept": True}
    assert exported[2]["OPENAI_API_KEY"] == "api-key-fixture"
    assert export_cockpit_tools([parsed.records[0]]).startswith("[\n  {")


def test_missing_required_identity_is_rejected_per_item_without_echoing_secret():
    result = parse_cockpit_tools(json.dumps([token_fixture(account_id="", email=""), api_key_fixture()]))

    assert result.items[0].status == "rejected"
    assert result.items[0].error.code == "missing_identity"
    assert result.items[1].status == "accepted"
    assert "api-key-fixture" not in repr(result)
