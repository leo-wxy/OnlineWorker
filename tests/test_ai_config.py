from __future__ import annotations

import os

import pytest
import yaml

from config import load_config
from core.ai.config import builtin_ai_service_raws, load_ai_config
from core.ai.contracts import AiScenarioConfig, AiServiceConfig


def test_ai_config_separates_service_connection_from_scenario_prompt():
    data = yaml.safe_load(
        """
ai:
  services:
    - id: openai_default
      name: OpenAI
      protocol: openai_compatible_chat
      base_url: https://api.openai.com/v1
      api_key: sk-openai
      models:
        - gpt-5.4
      default_model: gpt-5.4
      timeout_seconds: 20
      enabled: true
  scenarios:
    notification_summary:
      enabled: true
      service_id: openai_default
      model: gpt-5.4
      output_schema: notification_summary_v1
      fallback: local_notification_summary_rules
      limits:
        preview_title: 16
      prompt_template: |
        Return JSON for {{task_summary}}.
"""
    )

    ai_config = load_ai_config(data)

    service = ai_config.services["openai_default"]
    scenario = ai_config.scenarios["notification_summary"]
    assert isinstance(service, AiServiceConfig)
    assert isinstance(scenario, AiScenarioConfig)
    assert service.base_url == "https://api.openai.com/v1"
    assert service.api_key == "sk-openai"
    assert service.models == ("gpt-5.4",)
    assert not hasattr(service, "prompt_template")
    assert scenario.prompt_template == "Return JSON for {{task_summary}}.\n"
    assert scenario.service_id == "openai_default"
    assert scenario.limits == {"preview_title": 16}
    assert not hasattr(scenario, "base_url")
    assert not hasattr(scenario, "api_key_env")


def test_ai_config_adds_notification_summary_default_scenario():
    ai_config = load_ai_config({})

    assert set(ai_config.services) == {"openai_default", "anthropic_default"}
    assert ai_config.services["openai_default"].name == "OpenAI"
    assert ai_config.services["openai_default"].enabled is False
    assert ai_config.services["anthropic_default"].name == "Anthropic"
    assert ai_config.services["anthropic_default"].protocol == "anthropic_messages"
    scenario = ai_config.scenarios["notification_summary"]
    assert scenario.enabled is False
    assert scenario.service_id == "openai_default"
    assert scenario.output_schema == "notification_summary_v1"
    assert scenario.fallback == "local_notification_summary_rules"
    assert scenario.limits == {"preview_title": 16}
    assert "{{final_message}}" in scenario.prompt_template
    assert "complete short Chinese title" in scenario.prompt_template


def test_builtin_ai_service_defaults_come_from_provider_manifests():
    services = {service["id"]: service for service in builtin_ai_service_raws()}

    assert set(services) == {"openai_default", "anthropic_default"}
    assert services["openai_default"]["owner_provider_id"] == "codex"
    assert services["openai_default"]["api_key_env"] == "OPENAI_API_KEY"
    assert services["openai_default"]["default_for_scenarios"] is True
    assert services["anthropic_default"]["owner_provider_id"] == "claude"
    assert services["anthropic_default"]["api_key_env"] == "ANTHROPIC_API_KEY"


def test_ai_config_migrates_legacy_notification_summary_prompt():
    data = yaml.safe_load(
        """
ai:
  scenarios:
    notification_summary:
      enabled: true
      service_id: openai_default
      output_schema: notification_summary_v1
      fallback: local_notification_summary_rules
      limits:
        preview_title: 16
      prompt_template: |
        You summarize OnlineWorker task completion notifications.
        Return compact JSON with preview_title and summary.
        preview_title identifies the completed task.
        summary explains the completed result.

        Current task:
        {{task_summary}}

        Final assistant message:
        {{final_message}}
"""
    )

    scenario = load_ai_config(data).scenarios["notification_summary"]

    assert "complete short Chinese title" in scenario.prompt_template
    assert "Return compact JSON" not in scenario.prompt_template


def test_ai_config_falls_back_invalid_scenario_service_to_openai_default():
    data = yaml.safe_load(
        """
ai:
  services:
    - id: openai_default
      name: OpenAI
      models:
        - gpt-5.4
      default_model: gpt-5.4
  scenarios:
    notification_summary:
      enabled: true
      service_id: missing_service
      prompt_template: "Summarize {{final_message}}"
"""
    )

    ai_config = load_ai_config(data)

    assert ai_config.scenarios["notification_summary"].service_id == "openai_default"


def test_load_config_exposes_ai_namespace(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
schema_version: 2
ai:
  services:
    - id: anthropic_default
      name: Anthropic
      protocol: anthropic_messages
      endpoint: https://api.anthropic.com/v1/messages
      api_key: sk-claude
      models:
        - claude-sonnet-4-6
      default_model: claude-sonnet-4-6
  scenarios:
    notification_summary:
      enabled: true
      service_id: anthropic_default
      prompt_template: "Summarize {{final_message}}"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("ALLOWED_USER_ID", "123")
    monkeypatch.setenv("GROUP_CHAT_ID", "-456")

    config = load_config(str(config_path))

    assert "anthropic_default" in config.ai.services
    assert config.ai.services["anthropic_default"].endpoint == "https://api.anthropic.com/v1/messages"
    assert config.ai.services["anthropic_default"].api_key == "sk-claude"
    assert config.ai.scenarios["notification_summary"].enabled is True
    assert config.ai.scenarios["notification_summary"].prompt_template == "Summarize {{final_message}}"


def test_load_config_data_dir_migrates_legacy_ai_aliases(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
schema_version: 2
ai:
  services:
    - id: claude_default
      name: Anthropic
      protocol: claude_messages
      endpoint: https://api.anthropic.com/v1/messages
      api_key: sk-claude
      models:
        - claude-sonnet-4-6
      default_model: claude-sonnet-4-6
  scenarios:
    notification_summary:
      enabled: true
      service_id: claude_default
      prompt_template: "Summarize {{final_message}}"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "TELEGRAM_TOKEN=token\nALLOWED_USER_ID=123\nGROUP_CHAT_ID=-456\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("ALLOWED_USER_ID", raising=False)
    monkeypatch.delenv("GROUP_CHAT_ID", raising=False)

    config = load_config(data_dir=str(tmp_path))

    assert "anthropic_default" in config.ai.services
    assert "claude_default" not in config.ai.services
    assert config.ai.services["anthropic_default"].protocol == "anthropic_messages"
    assert config.ai.scenarios["notification_summary"].service_id == "anthropic_default"

    migrated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    services = migrated["ai"]["services"]
    assert services[0]["id"] == "anthropic_default"
    assert services[0]["protocol"] == "anthropic_messages"
    assert migrated["ai"]["scenarios"]["notification_summary"]["service_id"] == "anthropic_default"
