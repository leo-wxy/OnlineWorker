from __future__ import annotations

import json

from plugins.providers.builtin.codex.python.account_model import (
    classify_external_account,
    redacted_index_dto,
    upsert_account,
)
from plugins.providers.builtin.codex.python.compat import parse_cockpit_tools


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
    }


def _record(value, *, source="cockpit_tools"):
    return parse_cockpit_tools(json.dumps(value), source=source).records[0]


def test_stable_identity_is_deterministic_and_namespaced_by_auth_mode():
    token = _record(token_fixture())
    api_key = _record(api_key_fixture())

    assert token.identity_key == _record(token_fixture()).identity_key
    assert token.identity_key.startswith("token:")
    assert api_key.identity_key.startswith("apikey:")
    assert token.identity_key != api_key.identity_key
    assert "account-token" not in token.identity_key
    assert "api-key-fixture" not in api_key.identity_key


def test_same_identity_upsert_updates_in_place_and_preserves_unknown_fields():
    original_value = agent_identity_fixture()
    original_value["future_top_level"] = {"old": True}
    original = _record(original_value)
    incoming_value = agent_identity_fixture()
    incoming_value["email"] = "updated@example.com"
    incoming_value["agent_identity"].pop("future_nested")
    incoming = _record(incoming_value, source="oauth")
    records = [original]

    result = upsert_account(records, incoming)

    assert result.status == "updated"
    assert result.index == 0
    assert len(records) == 1
    assert records[0].credentials["email"] == "updated@example.com"
    assert records[0].credentials["future_top_level"] == {"old": True}
    assert records[0].credentials["agent_identity"]["future_nested"] == {"kept": True}


def test_duplicate_existing_identity_is_ambiguous_and_does_not_mutate_records():
    original = _record(token_fixture())
    records = [original, _record(token_fixture())]

    result = upsert_account(records, _record(token_fixture(email="updated@example.com")))

    assert result.status == "ambiguous"
    assert len(records) == 2
    assert records[0].credentials["email"] == "token@example.com"


def test_redacted_index_and_external_classification_never_expose_credentials():
    token = _record(token_fixture())
    api_key = _record(api_key_fixture())
    dto = redacted_index_dto(token, external_state="matched")

    assert classify_external_account(token, [token, api_key]) == "matched"
    assert classify_external_account(_record(token_fixture(account_id="different")), [token, api_key]) == "unmanaged"
    assert dto["externalState"] == "matched"
    serialized = json.dumps(dto)
    for secret in ("id-token-fixture", "access-token-fixture", "refresh-token-fixture"):
        assert secret not in serialized
    assert "credentials" not in dto
