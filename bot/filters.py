import logging
from telegram import Update
from telegram.ext import filters

logger = logging.getLogger(__name__)


class WhitelistFilter(filters.UpdateFilter):
    """只允许指定 user_id 的更新通过。"""

    def __init__(self, allowed_user_id: int):
        self.allowed_user_id = allowed_user_id
        super().__init__()

    def filter(self, update: Update) -> bool:
        if update.effective_user is None:
            logger.debug(f"[whitelist] 拒绝：effective_user 为 None")
            return False
        user_id = update.effective_user.id
        passed = user_id == self.allowed_user_id
        if not passed:
            logger.debug(f"[whitelist] 拒绝：user_id={user_id} != allowed={self.allowed_user_id}")
        return passed


class ThreadTopicTextFilter(filters.MessageFilter):
    """仅匹配已知 thread topic 中的文本消息。"""

    def __init__(self, state):
        self.state = state
        super().__init__()

    def filter(self, message) -> bool:
        topic_id = getattr(message, "message_thread_id", None)
        if topic_id is None:
            return False
        return self.state.find_thread_by_topic_id(topic_id) is not None
