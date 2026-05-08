import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# 授权按钮有效期（秒），默认 30 分钟
APPROVAL_TTL_SECONDS = 30 * 60


def build_confirm_keyboard(message_id: int) -> InlineKeyboardMarkup:
    """构建消息确认 inline keyboard。
    
    callback_data 格式：
      confirm:<message_id>
      cancel:<message_id>
    """
    buttons = [
        InlineKeyboardButton("✅ Confirm", callback_data=f"confirm:{message_id}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{message_id}"),
    ]
    return InlineKeyboardMarkup([buttons])


def build_approval_keyboard(message_id: int) -> InlineKeyboardMarkup:
    """构建沙盒权限授权 inline keyboard。

    callback_data 格式（含时间戳，用于 TTL 检测）：
      exec_allow:<message_id>:<ts>  — 允许本次
      exec_deny:<message_id>:<ts>   — 拒绝
    """
    ts = int(time.time())
    row1 = [
        InlineKeyboardButton("✅ Allow", callback_data=f"exec_allow:{message_id}:{ts}"),
        InlineKeyboardButton("❌ Deny", callback_data=f"exec_deny:{message_id}:{ts}"),
    ]
    return InlineKeyboardMarkup([row1])


def build_question_keyboard(
    message_id: int,
    options: list[dict],
    multiple: bool = False,
    custom: bool = True,
    selected: set | None = None,
) -> InlineKeyboardMarkup:
    """
    构建 provider question 选项 inline keyboard。

    单选模式：每个选项一行按钮，点击立即提交。
        callback_data: q_ans:<message_id>:<ts>:<option_index>

    多选模式：每个选项一行 toggle 按钮 + 底部确认按钮。
        toggle: q_tog:<message_id>:<ts>:<option_index>
        提交:  q_sub:<message_id>:<ts>

    自定义输入：末尾增加 "自定义输入" 按钮。
        callback_data: q_cus:<message_id>:<ts>

    Args:
        message_id: TG 消息 ID
        options: 选项列表 [{"label": "...", "description": "..."}, ...]
        multiple: 是否多选模式
        custom: 是否允许自定义输入
        selected: 多选模式下已选中的 option index 集合
    """
    ts = int(time.time())
    rows = []
    selected = selected or set()

    for idx, opt in enumerate(options):
        label = opt.get("label", f"选项 {idx + 1}")
        if multiple:
            # 多选：toggle 按钮，显示选中状态
            prefix = "✅ " if idx in selected else "⬜ "
            rows.append([
                InlineKeyboardButton(
                    prefix + label,
                    callback_data=f"q_tog:{message_id}:{ts}:{idx}",
                )
            ])
        else:
            # 单选：点击即提交
            # callback_data 最大 64 字节，label 不放进去，只用 index
            rows.append([
                InlineKeyboardButton(
                    label,
                    callback_data=f"q_ans:{message_id}:{ts}:{idx}",
                )
            ])

    # 自定义输入按钮
    if custom:
        rows.append([
            InlineKeyboardButton(
                "✍️ 自定义输入",
                callback_data=f"q_cus:{message_id}:{ts}",
            )
        ])

    # 多选模式：确认提交按钮
    if multiple:
        count = len(selected)
        submit_label = f"📩 确认提交（已选 {count}）" if count else "📩 确认提交"
        rows.append([
            InlineKeyboardButton(
                submit_label,
                callback_data=f"q_sub:{message_id}:{ts}",
            )
        ])

    return InlineKeyboardMarkup(rows)


def build_thread_control_keyboard(*, allow_interrupt: bool = True) -> InlineKeyboardMarkup:
    """构建 thread Topic 的 onlineWorker 控制按钮。"""
    rows = [
        [
            InlineKeyboardButton("帮助", callback_data="threadctl:help"),
            InlineKeyboardButton("历史", callback_data="threadctl:history"),
        ]
    ]

    final_row = []
    if allow_interrupt:
        final_row.append(InlineKeyboardButton("中断", callback_data="threadctl:interrupt"))
    final_row.append(InlineKeyboardButton("归档", callback_data="threadctl:archive"))
    rows.append(final_row)
    return InlineKeyboardMarkup(rows)


# Question 按钮有效期（秒），默认 30 分钟
QUESTION_TTL_SECONDS = 30 * 60
COMMAND_WRAPPER_TTL_SECONDS = 30 * 60


def build_command_wrapper_keyboard(
    wrapper_id: int,
    options: list,
) -> InlineKeyboardMarkup:
    """构建通用命令 wrapper keyboard。"""
    ts = int(time.time())
    rows = []

    for idx, option in enumerate(options):
        label = getattr(option, "label", None) or f"选项 {idx + 1}"
        rows.append([
            InlineKeyboardButton(
                label,
                callback_data=f"cmdw_sel:{wrapper_id}:{ts}:{idx}",
            )
        ])

    rows.append([
        InlineKeyboardButton("🔄 重新读取", callback_data=f"cmdw_ref:{wrapper_id}:{ts}"),
        InlineKeyboardButton("❌ 关闭", callback_data=f"cmdw_can:{wrapper_id}:{ts}"),
    ])
    return InlineKeyboardMarkup(rows)


def parse_question_callback(data: str) -> tuple[str, int, int, int, bool]:
    """
    解析 question 系列 callback_data，返回 (action, msg_id, ts, option_index, is_expired)。

    支持的格式：
        q_ans:<msg_id>:<ts>:<option_index>   — 单选直接提交
        q_tog:<msg_id>:<ts>:<option_index>   — 多选 toggle
        q_sub:<msg_id>:<ts>                  — 多选确认提交
        q_cus:<msg_id>:<ts>                  — 自定义输入

    返回:
        action: "q_ans" | "q_tog" | "q_sub" | "q_cus"
        msg_id: TG 消息 ID
        ts: 时间戳
        option_index: 选项索引（q_sub/q_cus 时为 -1）
        is_expired: 是否过期
    """
    parts = data.split(":")
    try:
        action = parts[0]
        msg_id = int(parts[1])
        ts = int(parts[2])
        option_idx = int(parts[3]) if len(parts) > 3 else -1
        expired = (time.time() - ts) > QUESTION_TTL_SECONDS
        return action, msg_id, ts, option_idx, expired
    except (IndexError, ValueError):
        return "unknown", 0, 0, -1, True


def parse_command_wrapper_callback(data: str) -> tuple[str, int, int, int, bool]:
    """
    解析命令 wrapper callback_data，返回 (action, wrapper_id, ts, option_index, is_expired)。

    支持的格式：
        cmdw_sel:<wrapper_id>:<ts>:<option_index>
        cmdw_ref:<wrapper_id>:<ts>
        cmdw_can:<wrapper_id>:<ts>
    """
    parts = data.split(":")
    try:
        action = parts[0]
        wrapper_id = int(parts[1])
        ts = int(parts[2])
        option_idx = int(parts[3]) if len(parts) > 3 else -1
        expired = (time.time() - ts) > COMMAND_WRAPPER_TTL_SECONDS
        return action, wrapper_id, ts, option_idx, expired
    except (IndexError, ValueError):
        return "unknown", 0, 0, -1, True


def parse_approval_callback(data: str) -> tuple[str, int, bool]:
    """
    解析授权 callback_data，返回 (action, msg_id, is_expired)。
    格式：<action>:<msg_id>[:<ts>]
    """
    parts = data.split(":")
    action = parts[0]
    try:
        msg_id = int(parts[1])
    except (IndexError, ValueError):
        return action, 0, True

    # 检查 TTL
    if len(parts) >= 3:
        try:
            ts = int(parts[2])
            expired = (time.time() - ts) > APPROVAL_TTL_SECONDS
        except ValueError:
            expired = True
    else:
        # 旧格式（无时间戳）：bot 重启后视为过期
        expired = True

    return action, msg_id, expired
