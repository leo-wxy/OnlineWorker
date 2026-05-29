from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.ai.client import AiHttpResponse
from core.ai.contracts import AiConfig, AiScenarioConfig, AiServiceConfig
from core.ai.scenarios import AiScenarioResult, run_ai_scenario
from core.ai.templates import render_prompt_template


class FakeAiClient:
    def __init__(self, response: AiHttpResponse | Exception):
        self.response = response
        self.calls: list[dict] = []

    async def complete(self, *, service, model, prompt, timeout_seconds):
        self.calls.append(
            {
                "service": service,
                "model": model,
                "prompt": prompt,
                "timeout_seconds": timeout_seconds,
            }
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _config(*, enabled: bool = True) -> AiConfig:
    return AiConfig(
        services={
            "openai_default": AiServiceConfig(
                id="openai_default",
                name="OpenAI",
                protocol="openai_compatible_chat",
                base_url="https://api.openai.com/v1",
                api_key="sk-openai",
                models=("gpt-5.4",),
                default_model="gpt-5.4",
                timeout_seconds=7,
                enabled=True,
            )
        },
        scenarios={
            "notification_summary": AiScenarioConfig(
                id="notification_summary",
                enabled=enabled,
                service_id="openai_default",
                model="",
                output_schema="notification_summary_v1",
                fallback="local_notification_summary_rules",
                limits={"preview_title": 16},
                prompt_template="Task: {{task_summary}}\nFinal: {{final_message}}",
            )
        },
    )


def test_render_prompt_template_replaces_known_variables_only():
    assert (
        render_prompt_template(
            "{{task_summary}} -> {{missing}} -> {{final_message}}",
            {"task_summary": "任务", "final_message": "完成"},
        )
        == "任务 ->  -> 完成"
    )


@pytest.mark.asyncio
async def test_run_ai_scenario_returns_valid_notification_summary():
    client = FakeAiClient(
        AiHttpResponse(
            text='{"preview_title": "优化任务通知", "summary": "完成 AI 摘要接入。"}',
            raw={"id": "chatcmpl-test"},
        )
    )

    result = await run_ai_scenario(
        "notification_summary",
        {"task_summary": "通知文案", "final_message": "已完成"},
        config=_config(),
        client=client,
    )

    assert result == AiScenarioResult(
        ok=True,
        data={
            "preview_title": "优化任务通知",
            "summary": "完成 AI 摘要接入。",
        },
        fallback="",
        error="",
    )
    assert client.calls[0]["model"] == "gpt-5.4"
    assert client.calls[0]["timeout_seconds"] == 7
    assert "通知文案" in client.calls[0]["prompt"]


@pytest.mark.asyncio
async def test_run_ai_scenario_limits_preview_title_but_preserves_summary_text():
    client = FakeAiClient(
        AiHttpResponse(
            text='{"preview_title": "1234567890", "summary": "abcdefghij"}',
            raw={},
        )
    )
    config = _config()
    scenario = config.scenarios["notification_summary"]
    config.scenarios["notification_summary"] = AiScenarioConfig(
        id=scenario.id,
        enabled=scenario.enabled,
        service_id=scenario.service_id,
        output_schema=scenario.output_schema,
        fallback=scenario.fallback,
        limits={"preview_title": 4, "summary": 6},
        prompt_template=scenario.prompt_template,
    )

    result = await run_ai_scenario(
        "notification_summary",
        {"task_summary": "通知文案", "final_message": "已完成"},
        config=config,
        client=client,
    )

    assert result.ok is True
    assert result.data == {
        "preview_title": "1234",
        "summary": "abcdefghij",
    }


@pytest.mark.asyncio
async def test_run_ai_scenario_drops_trailing_partial_ascii_preview_title():
    client = FakeAiClient(
        AiHttpResponse(
            text='{"preview_title": "Session 归档菜单与 Codex 映射", "summary": "已修复归档菜单。"}',
            raw={},
        )
    )
    config = _config()

    result = await run_ai_scenario(
        "notification_summary",
        {"task_summary": "Session 归档菜单", "final_message": "已完成"},
        config=config,
        client=client,
    )

    assert result.ok is True
    assert result.data["preview_title"] == "Session 归档菜单"
    assert result.data["summary"] == "已修复归档菜单。"


@pytest.mark.asyncio
async def test_run_ai_scenario_does_not_cut_notification_summary_at_legacy_limit():
    summary = (
        "已完成源码侧 Session 右键 Archive 功能及真实后端归档链路：前端 SessionBrowser 增加右键归档入口，"
        "Tauri 新增 archive_provider_session 命令，后端接入真实 provider archive。"
    )
    client = FakeAiClient(
        AiHttpResponse(
            text='{"preview_title": "Phase 9 Session", "summary": "%s"}' % summary,
            raw={},
        )
    )
    config = _config()
    scenario = config.scenarios["notification_summary"]
    config.scenarios["notification_summary"] = AiScenarioConfig(
        id=scenario.id,
        enabled=scenario.enabled,
        service_id=scenario.service_id,
        output_schema=scenario.output_schema,
        fallback=scenario.fallback,
        limits={"preview_title": 16, "summary": 80},
        prompt_template=scenario.prompt_template,
    )

    result = await run_ai_scenario(
        "notification_summary",
        {"task_summary": "Phase 9 Session", "final_message": "已完成"},
        config=config,
        client=client,
    )

    assert result.ok is True
    assert result.data["preview_title"] == "Phase 9 Session"
    assert result.data["summary"] == summary
    assert result.data["summary"].endswith("provider archive。")
    assert not result.data["summary"].endswith("archiv")


@pytest.mark.asyncio
async def test_run_ai_scenario_returns_fallback_when_disabled():
    client = FakeAiClient(AiHttpResponse(text="{}", raw={}))

    result = await run_ai_scenario(
        "notification_summary",
        {"task_summary": "通知文案", "final_message": "已完成"},
        config=_config(enabled=False),
        client=client,
    )

    assert result.ok is False
    assert result.fallback == "local_notification_summary_rules"
    assert result.error == "scenario_disabled"
    assert client.calls == []


@pytest.mark.asyncio
async def test_run_ai_scenario_returns_fallback_on_invalid_output():
    client = FakeAiClient(AiHttpResponse(text='{"preview_title": ""}', raw={}))

    result = await run_ai_scenario(
        "notification_summary",
        {"task_summary": "通知文案", "final_message": "已完成"},
        config=_config(),
        client=client,
    )

    assert result.ok is False
    assert result.fallback == "local_notification_summary_rules"
    assert result.error == "invalid_output"


@pytest.mark.asyncio
async def test_run_ai_scenario_returns_fallback_on_client_error():
    client = FakeAiClient(RuntimeError("timeout"))

    result = await run_ai_scenario(
        "notification_summary",
        {"task_summary": "通知文案", "final_message": "已完成"},
        config=_config(),
        client=client,
    )

    assert result.ok is False
    assert result.fallback == "local_notification_summary_rules"
    assert result.error == "client_error"


@pytest.mark.asyncio
async def test_run_ai_scenario_uses_selected_service_model_not_scenario_model():
    client = FakeAiClient(
        AiHttpResponse(
            text='{"preview_title": "切换服务", "summary": "只调用场景选择的服务。"}',
            raw={},
        )
    )
    config = AiConfig(
        services={
            "openai_default": AiServiceConfig(
                id="openai_default",
                name="OpenAI",
                protocol="openai_compatible_chat",
                base_url="https://api.openai.com/v1",
                api_key="sk-openai",
                models=("gpt-5.4",),
                default_model="gpt-5.4",
                timeout_seconds=7,
                enabled=True,
            ),
            "claude_default": AiServiceConfig(
                id="claude_default",
                name="Claude",
                protocol="claude_messages",
                endpoint="https://api.anthropic.com/v1/messages",
                api_key="sk-claude",
                models=("claude-sonnet-4-6",),
                default_model="claude-sonnet-4-6",
                timeout_seconds=9,
                enabled=True,
            ),
        },
        scenarios={
            "notification_summary": AiScenarioConfig(
                id="notification_summary",
                enabled=True,
                service_id="claude_default",
                model="gpt-5.4",
                output_schema="notification_summary_v1",
                fallback="local_notification_summary_rules",
                prompt_template="Final: {{final_message}}",
            )
        },
    )

    result = await run_ai_scenario(
        "notification_summary",
        {"final_message": "done"},
        config=config,
        client=client,
    )

    assert result.ok is True
    assert len(client.calls) == 1
    assert client.calls[0]["service"].id == "claude_default"
    assert client.calls[0]["model"] == "claude-sonnet-4-6"
    assert client.calls[0]["timeout_seconds"] == 9
