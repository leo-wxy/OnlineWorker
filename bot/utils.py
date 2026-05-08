# bot/utils.py
"""公共工具函数：发消息、文本截断、UTF-16 长度计算。"""
import asyncio
import logging
from typing import Optional

from telegram import Bot
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

MAX_TG_LEN = 4096


class TopicNotFoundError(Exception):
    """Telegram forum topic 已被删除（Message thread not found）。"""
    def __init__(self, topic_id: int, original: Exception):
        self.topic_id = topic_id
        self.original = original
        super().__init__(f"Topic {topic_id} not found")


def utf16_len(text: str) -> int:
    """计算文本的 UTF-16 码元数（Telegram API 按此计算长度限制）。"""
    return len(text.encode("utf-16-le")) // 2


def truncate_text(text: str, limit: int = MAX_TG_LEN) -> str:
    """
    截断文本到 limit 个 UTF-16 码元以内。
    Telegram API 的 4096 限制按 UTF-16 码元计算，而非 Python 字符数。
    含 emoji（如 💭🤖🔧）的文本，Python len() < 实际 UTF-16 码元数。
    截断时追加说明，并尝试闭合可能断开的 inline code（`）标记。
    """
    if utf16_len(text) <= limit:
        return text
    suffix = f"\n…[输出已截断，共 {len(text)} 字符]"
    suffix_u16 = utf16_len(suffix)
    budget = limit - suffix_u16
    truncated_chars = []
    used = 0
    for ch in text:
        ch_u16 = utf16_len(ch)
        if used + ch_u16 > budget:
            break
        truncated_chars.append(ch)
        used += ch_u16
    truncated = "".join(truncated_chars)
    if truncated.count("`") % 2 == 1:
        if used + 1 > budget:
            truncated = truncated[:-1]
        truncated += "`"
    return truncated + suffix


async def send_to_group(
    bot: Bot,
    group_chat_id: int,
    text: str,
    topic_id: Optional[int] = None,
    _max_retries: int = 2,
    **kwargs,
):
    """发消息到群组，可选指定 topic。超长自动截断。网络错误时重试。返回 Message 对象。"""
    text = truncate_text(text)
    for attempt in range(_max_retries + 1):
        try:
            return await bot.send_message(
                chat_id=group_chat_id,
                text=text,
                message_thread_id=topic_id,
                **kwargs,
            )
        except BadRequest as e:
            if "message thread not found" in str(e).lower() and topic_id is not None:
                raise TopicNotFoundError(topic_id, e) from e
            raise
        except Exception as e:
            err_str = str(e).lower()
            is_network = isinstance(e, (ConnectionError, TimeoutError, OSError)) or any(
                kw in err_str for kw in ("connecterror", "timeout", "broken", "reset", "eof")
            )
            if is_network and attempt < _max_retries:
                wait = 1.0 * (attempt + 1)
                logger.warning(f"[send_to_group] 网络错误，{wait}s 后重试 ({attempt+1}/{_max_retries}): {e}")
                await asyncio.sleep(wait)
                continue
            raise
