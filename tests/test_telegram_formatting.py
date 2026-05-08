from core.telegram_formatting import format_telegram_assistant_final_text


def test_format_telegram_assistant_final_text_renders_supported_markdown_subset():
    result = format_telegram_assistant_final_text(
        "## 已完成\n\n- 收口 App final render\n- 补齐 TG fallback\n\n```python\nprint('ok')\n```"
    )

    assert result.parse_mode == "HTML"
    assert result.fallback_text.startswith("## 已完成")
    assert "<b>已完成</b>" in result.text
    assert "• 收口 App final render" in result.text
    assert "<pre><code class=\"language-python\">" in result.text
    assert "print('ok')" in result.text
    assert "<br>" not in result.text


def test_format_telegram_assistant_final_text_uses_telegram_supported_newlines():
    result = format_telegram_assistant_final_text(
        "第一行\n第二行\n\n> 引用一\n> 引用二\n\n1. 步骤一\n2. 步骤二"
    )

    assert result.parse_mode == "HTML"
    assert "<br>" not in result.text
    assert "第一行\n第二行" in result.text
    assert "<blockquote>引用一\n引用二</blockquote>" in result.text
    assert "1. 步骤一\n2. 步骤二" in result.text


def test_format_telegram_assistant_final_text_falls_back_when_markup_exceeds_budget():
    result = format_telegram_assistant_final_text(
        "```python\nprint('x')\n```",
        max_length=12,
    )

    assert result.parse_mode is None
    assert result.text == "```python\nprint('x')\n```"
    assert result.fallback_text == result.text
