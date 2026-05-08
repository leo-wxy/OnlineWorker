# tests/test_common_utils.py
"""
测试 bot/utils.py 中的纯逻辑函数：utf16_len 和 truncate_text。
不涉及任何网络/Telegram API，完全同步。
"""
import pytest
from bot.utils import utf16_len, truncate_text, MAX_TG_LEN


# ── utf16_len ─────────────────────────────────────────────────────────────────

class TestUtf16Len:
    def test_ascii_len(self):
        assert utf16_len("hello") == 5

    def test_empty_string(self):
        assert utf16_len("") == 0

    def test_chinese_chars(self):
        # 每个中文字符在 UTF-16 中占 1 个码元
        assert utf16_len("你好") == 2

    def test_emoji_surrogate_pair(self):
        # emoji 如 💭 在 UTF-16 占 2 个码元（代理对）
        assert utf16_len("💭") == 2

    def test_mixed_ascii_emoji(self):
        # "Hi" (2) + "🤖" (2) = 4
        assert utf16_len("Hi🤖") == 4


# ── truncate_text ─────────────────────────────────────────────────────────────

class TestTruncateText:
    def test_short_text_unchanged(self):
        text = "hello world"
        assert truncate_text(text) == text

    def test_exact_limit_unchanged(self):
        # 恰好 4096 个 ASCII 字符，不应截断
        text = "a" * MAX_TG_LEN
        assert truncate_text(text) == text

    def test_over_limit_truncated(self):
        # 超出限制应被截断，且包含截断说明
        text = "a" * (MAX_TG_LEN + 100)
        result = truncate_text(text)
        assert utf16_len(result) <= MAX_TG_LEN
        assert "输出已截断" in result

    def test_custom_limit(self):
        text = "a" * 200
        result = truncate_text(text, limit=100)
        assert utf16_len(result) <= 100
        assert "输出已截断" in result

    def test_emoji_over_limit_truncated(self):
        # 500 个 emoji，每个占 2 个 UTF-16 码元 → 1000 个码元，使用 limit=50 触发截断
        text = "🔧" * 500
        result = truncate_text(text, limit=50)
        assert utf16_len(result) <= 50

    def test_unclosed_backtick_closed(self):
        # 截断后若存在奇数个反引号，应补一个
        # 构造：前缀 + ` + 大量填充使截断恰好发生在 ` 后面
        prefix = "`code"
        padding = "x" * (MAX_TG_LEN * 2)
        text = prefix + padding
        result = truncate_text(text)
        # 反引号数量应为偶数（已闭合）
        assert result.count("`") % 2 == 0

    def test_result_utf16_within_limit(self):
        # 随机混合内容：中文 + ASCII + emoji
        text = "你好" * 500 + "hello" * 200 + "💭" * 100
        result = truncate_text(text)
        assert utf16_len(result) <= MAX_TG_LEN

    def test_empty_string_unchanged(self):
        assert truncate_text("") == ""
