import pytest
from bot.keyboards import build_confirm_keyboard

def test_build_confirm_keyboard_structure():
    kb = build_confirm_keyboard(message_id=42)
    assert hasattr(kb, "inline_keyboard")
    buttons = kb.inline_keyboard[0]  # 第一行
    assert len(buttons) == 2
    labels = [b.text for b in buttons]
    assert "✅ Confirm" in labels
    assert "❌ Cancel" in labels

def test_confirm_callback_data_contains_message_id():
    kb = build_confirm_keyboard(message_id=42)
    buttons = kb.inline_keyboard[0]
    confirm_btn = next(b for b in buttons if "Confirm" in b.text)
    assert "42" in confirm_btn.callback_data

def test_cancel_callback_data_contains_message_id():
    kb = build_confirm_keyboard(message_id=42)
    buttons = kb.inline_keyboard[0]
    cancel_btn = next(b for b in buttons if "Cancel" in b.text)
    assert "42" in cancel_btn.callback_data
