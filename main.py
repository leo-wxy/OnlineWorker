import argparse
import fcntl
import json
import logging
import logging.handlers
import os
import sys
import time
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    TypeHandler,
    filters,
)
from telegram.request import HTTPXRequest
from config import load_config, default_data_dir, set_data_dir
from core.state import AppState
from core.storage import load_storage
from core.lifecycle import LifecycleManager
from bot.filters import WhitelistFilter
from bot.handlers.common import (
    make_start_handler, make_ping_handler, make_echo_handler,
    make_status_handler, make_help_handler, make_active_handler,
    make_restart_handler, make_stop_handler,
)
from bot.handlers.workspace import (
    make_workspace_handler, make_ws_open_callback_handler, make_thread_open_callback_handler,
    make_cli_handler, make_cli_callback_handler,
)
from bot.handlers.thread import (
    make_new_thread_handler, make_list_thread_handler,
    make_archive_thread_handler, make_skills_handler, make_history_handler,
)
from bot.handlers.slash import make_slash_command_handler
from bot.handlers.message import make_message_handler, make_callback_handler

logger = logging.getLogger(__name__)

_DEFAULT_LOCK_FILE = "/tmp/onlineworker_bot.lock"

# 持有文件锁的文件对象，进程退出时 OS 自动释放
_lock_fh = None


def _acquire_flock(lock_file: str = _DEFAULT_LOCK_FILE) -> None:
    """用 fcntl.flock 独占锁保证单实例。拿不到锁说明已有实例在运行，直接退出。"""
    global _lock_fh
    _lock_fh = open(lock_file, "w")
    try:
        fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[onlineWorker] 已有实例在运行，退出。", file=sys.stderr)
        sys.exit(1)
    # 写入当前 PID，方便排查
    _lock_fh.write(str(os.getpid()))
    _lock_fh.flush()


MAX_RAPID_CRASHES = 5       # 连续快速崩溃上限
RAPID_CRASH_WINDOW = 60     # 秒内崩溃算"快速崩溃"


def _print_provider_session_bridge_result(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def _run_provider_session_bridge(
    provider_id: str,
    operation: str,
    *,
    session_id: str | None = None,
    workspace_dir: str | None = None,
    limit: int = 50,
) -> int:
    from core.provider_session_bridge import (
        list_provider_session_rows,
        read_provider_session_rows,
        send_provider_session_message,
    )

    normalized_provider = str(provider_id or "").strip()
    if not normalized_provider:
        raise ValueError("provider_id is required")

    normalized_operation = str(operation or "").strip().lower()
    if normalized_operation == "list":
        _print_provider_session_bridge_result(
            list_provider_session_rows(normalized_provider, limit_per_workspace=limit)
        )
        return 0

    if normalized_operation == "read":
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("session_id is required for read operation")
        _print_provider_session_bridge_result(
            read_provider_session_rows(
                normalized_provider,
                normalized_session_id,
                limit=limit,
                sessions_dir=workspace_dir,
            )
        )
        return 0

    if normalized_operation == "send":
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("session_id is required for send operation")
        asyncio.run(
            send_provider_session_message(
                normalized_provider,
                normalized_session_id,
                session_id if False else "",  # unreachable placeholder removed below
            )
        )
        _print_provider_session_bridge_result({"ok": True})
        return 0

    raise ValueError(f"unsupported provider session bridge operation: {operation}")


async def _log_raw_update(update: Update, context) -> None:
    """记录原始 update 类型，优先确认 callback_query 是否真的送达当前实例。"""
    if not isinstance(update, Update):
        return

    kinds: list[str] = []
    if update.message is not None:
        kinds.append("message")
    if update.edited_message is not None:
        kinds.append("edited_message")
    if update.callback_query is not None:
        kinds.append("callback_query")
    if update.inline_query is not None:
        kinds.append("inline_query")
    if update.chosen_inline_result is not None:
        kinds.append("chosen_inline_result")

    if not kinds:
        return

    if update.callback_query is not None:
        query = update.callback_query
        logger.info(
            "[raw-update] id=%s kinds=%s callback_id=%s data=%r from=%s msg_id=%s chat_id=%s",
            update.update_id,
            ",".join(kinds),
            getattr(query, "id", ""),
            getattr(query, "data", None),
            getattr(getattr(query, "from_user", None), "id", None),
            getattr(getattr(query, "message", None), "message_id", None),
            getattr(getattr(getattr(query, "message", None), "chat", None), "id", None),
        )
        return

    logger.info("[raw-update] id=%s kinds=%s", update.update_id, ",".join(kinds))


async def _log_application_error(update: object, context) -> None:
    """记录 PTB update 处理链中的未捕获异常。"""
    logger.error(
        "[ptb-error] update_type=%s error=%s",
        type(update).__name__ if update is not None else "None",
        getattr(context, "error", None),
        exc_info=getattr(context, "error", None),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="OnlineWorker Telegram Bot")
    parser.add_argument("--data-dir", default=None,
                        help="Data directory for config/state/logs (default: use CWD)")
    parser.add_argument(
        "--claude-hook-bridge",
        action="store_true",
        help="Run once as Claude hook bridge relay and exit",
    )
    parser.add_argument(
        "--codex-hook-bridge",
        action="store_true",
        help="Run once as Codex hook bridge relay and exit",
    )
    parser.add_argument(
        "--provider-session-bridge",
        action="store_true",
        help="Run once as provider session bridge and exit",
    )
    parser.add_argument("--provider-id", default=None)
    parser.add_argument("--provider-session-op", default=None)
    parser.add_argument("--provider-session-id", default=None)
    parser.add_argument("--provider-workspace-dir", default=None)
    parser.add_argument("--provider-limit", type=int, default=50)
    args, _ = parser.parse_known_args()

    data_dir = args.data_dir or default_data_dir()
    set_data_dir(data_dir)

    if args.claude_hook_bridge:
        from plugins.providers.builtin.claude.python.hook_bridge import run_claude_hook_bridge_once

        raise SystemExit(run_claude_hook_bridge_once(data_dir))
    if args.codex_hook_bridge:
        from plugins.providers.builtin.codex.python.hook_bridge import run_codex_hook_bridge_once

        raise SystemExit(run_codex_hook_bridge_once(data_dir))
    if args.provider_session_bridge:
        raise SystemExit(
            _run_provider_session_bridge(
                args.provider_id,
                args.provider_session_op,
                session_id=args.provider_session_id,
                workspace_dir=args.provider_workspace_dir,
                limit=args.provider_limit,
            )
        )

    # Resolve paths based on data_dir ----------------------------------------
    if data_dir:
        lock_file = os.path.join(data_dir, "onlineworker.lock")
        log_file = os.path.join(data_dir, "onlineworker.log")
    else:
        lock_file = _DEFAULT_LOCK_FILE        # /tmp/onlineworker_bot.lock
        log_file = "/tmp/onlineworker.log"    # backward compat

    _acquire_flock(lock_file)

    cfg = load_config(data_dir=data_dir)

    # 日志轮转：最多 10MB，保留 3 个备份（onlineworker.log, .log.1, .log.2, .log.3）
    log_level = getattr(logging, cfg.log_level.upper(), logging.INFO)
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # 清除已有 handler（防止崩溃重启后重复添加）
    root_logger.handlers.clear()

    # RotatingFileHandler: 10MB per file, keep 3 backups
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(file_handler)

    # 同时输出到 stdout（方便 launchd 抓取和调试）
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(stream_handler)

    rapid_crashes = 0
    last_crash_time = 0.0

    while True:
        try:
            storage = load_storage()
            state = AppState(storage=storage, config=cfg)

            whitelist = WhitelistFilter(allowed_user_id=cfg.allowed_user_id)
            gid = cfg.group_chat_id

            app = (
                Application.builder()
                .token(cfg.telegram_token)
                .request(HTTPXRequest(read_timeout=20, write_timeout=20, connect_timeout=10))
                .build()
            )

            app.add_handler(TypeHandler(Update, _log_raw_update), group=-1)
            app.add_error_handler(_log_application_error)

            # 所有 Telegram /xxx 统一收口到 slash router，由它按 global/workspace/thread 分流。
            app.add_handler(MessageHandler(
                whitelist & filters.TEXT & filters.Regex(r'^/'),
                make_slash_command_handler(state, gid, cfg),
                block=False,
            ))

            app.add_handler(make_ws_open_callback_handler(state, gid))
            app.add_handler(make_thread_open_callback_handler(state, gid))
            app.add_handler(make_cli_callback_handler(state, gid, cfg))

            app.add_handler(MessageHandler(
                whitelist & filters.TEXT & ~filters.Regex(r'^/'),
                make_message_handler(state, gid),
                block=False,
            ))
            app.add_handler(MessageHandler(
                whitelist & filters.PHOTO,
                make_message_handler(state, gid),
                block=False,
            ))

            app.add_handler(CallbackQueryHandler(make_callback_handler(state, gid)))

            # Lifecycle management
            lifecycle = LifecycleManager(state, storage, gid, cfg)
            app.post_init = lifecycle.post_init
            app.post_shutdown = lifecycle.post_shutdown

            logger.info(f"onlineWorker 启动，允许用户 ID：{cfg.allowed_user_id}，群组 ID：{gid}")
            # 外层有崩溃重试循环，不能让 PTB 在每次失败后关闭当前事件循环。
            app.run_polling(
                drop_pending_updates=True,
                close_loop=False,
                allowed_updates=["message", "callback_query"],
            )
            # run_polling 正常退出（用户 Ctrl-C 或收到 SIGTERM）→ 退出循环
            logger.info("onlineWorker 正常退出")
            break

        except KeyboardInterrupt:
            logger.info("收到 KeyboardInterrupt，退出")
            break
        except SystemExit:
            raise  # 让 sys.exit() 正常工作
        except Exception as e:
            now = time.time()
            if now - last_crash_time < RAPID_CRASH_WINDOW:
                rapid_crashes += 1
            else:
                rapid_crashes = 1
            last_crash_time = now

            if rapid_crashes >= MAX_RAPID_CRASHES:
                logger.critical(
                    f"onlineWorker {RAPID_CRASH_WINDOW}s 内连续崩溃 {rapid_crashes} 次，放弃重试，退出。"
                    f"最后错误：{e}"
                )
                sys.exit(1)

            delay = min(5 * rapid_crashes, 30)
            logger.error(
                f"onlineWorker 崩溃（第 {rapid_crashes} 次），{delay}s 后自动重启。错误：{e}",
                exc_info=True,
            )
            time.sleep(delay)


if __name__ == "__main__":
    main()
