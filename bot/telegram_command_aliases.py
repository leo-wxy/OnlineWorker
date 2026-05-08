import json
import logging
import os

from config import get_data_dir

logger = logging.getLogger(__name__)

COMMAND_REGISTRY_FILENAME = "command_registry.json"


def resolve_registered_command_alias(name: str) -> str:
    normalized = (name or "").strip().lower()
    if not normalized:
        return normalized

    data_dir = get_data_dir()
    if not data_dir:
        return normalized

    path = os.path.join(data_dir, COMMAND_REGISTRY_FILENAME)
    if not os.path.exists(path):
        return normalized

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as error:
        logger.debug("[command-alias] 读取 registry 失败，跳过 alias 解析：%s", error)
        return normalized

    for command in payload.get("commands", []):
        if not isinstance(command, dict):
            continue
        if str(command.get("status") or "").strip().lower() != "active":
            continue

        original_name = str(command.get("name") or "").strip().lower()
        telegram_name = str(command.get("telegramName") or original_name).strip().lower()
        if not original_name or not telegram_name:
            continue

        if telegram_name == normalized:
            return original_name

    return normalized
