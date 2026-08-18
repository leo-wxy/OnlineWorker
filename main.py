import argparse
import asyncio
import fcntl
import json
import logging
import logging.handlers
import os
import re
import sys
import time


_ACCOUNT_FEATURE_FLAGS = {
    "--account-feature-list",
    "--account-feature-action",
    "--account-feature-worker",
}
_ACCOUNT_FEATURE_MAX_INPUT = 8 * 1024 * 1024


def _account_feature_arg(argv: list[str], name: str) -> str:
    indexes = [index for index, value in enumerate(argv) if value == name]
    if len(indexes) != 1 or indexes[0] + 1 >= len(argv):
        return ""
    return argv[indexes[0] + 1].strip()


def _print_account_feature_envelope(
    payload: object, *, request_id: str = "", newline: bool = False
) -> None:
    if request_id and isinstance(payload, dict):
        payload = {**payload, "requestId": request_id}
    try:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        fallback = _account_feature_error(
            "invalid_response", "账号功能返回了无效数据。"
        )
        if request_id:
            fallback["requestId"] = request_id
        encoded = json.dumps(fallback, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(encoded + ("\n" if newline else ""))
    sys.stdout.flush()


def _account_feature_error(code: str, message: str, *, retryable: bool = False) -> dict:
    return {
        "ok": False,
        "data": None,
        "error": {"code": code, "message": message, "retryable": retryable},
    }


def _read_account_feature_request() -> dict | None:
    raw = sys.stdin.buffer.read(_ACCOUNT_FEATURE_MAX_INPUT + 1)
    if len(raw) > _ACCOUNT_FEATURE_MAX_INPUT:
        return None
    try:
        request = json.loads(raw or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return request if isinstance(request, dict) else None


def _account_feature_payload_has_reserved_context(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"data_root", "dataRoot", "native_paths", "nativePaths"}
            or _account_feature_payload_has_reserved_context(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_account_feature_payload_has_reserved_context(child) for child in value)
    return False


def _account_feature_list_envelope() -> dict:
    from dataclasses import asdict

    from core.account_features import (
        account_feature_load_failures,
        list_account_features,
    )

    features = list_account_features()
    return {
        "ok": True,
        "data": {
            "features": [asdict(feature) for feature in features],
            "failures": account_feature_load_failures(),
        },
        "error": None,
    }


def _account_feature_action_envelope(
    feature_id: str, action: str, request: dict, *, discover: bool
) -> dict:
    from core.account_features import (
        account_feature_backend_entry,
        account_feature_backend_module,
        list_account_features,
    )

    if not feature_id or not action:
        return _account_feature_error("invalid_request", "账号功能请求无效。")
    payload = request.get("payload")
    trusted_context = request.get("trusted_context")
    if not isinstance(trusted_context, dict):
        return _account_feature_error("invalid_context", "账号功能上下文无效。")
    data_root = trusted_context.get("data_root")
    native_paths = trusted_context.get("native_paths", [])
    if (
        not isinstance(data_root, str)
        or not os.path.isabs(data_root)
        or not isinstance(native_paths, list)
    ):
        return _account_feature_error("invalid_context", "账号功能上下文无效。")
    if _account_feature_payload_has_reserved_context(payload):
        return _account_feature_error("invalid_payload", "账号功能参数包含保留字段。")

    if discover:
        list_account_features()
    backend_path = account_feature_backend_entry(feature_id)
    backend_module = account_feature_backend_module(feature_id)
    if backend_path is None or backend_module is None:
        return _account_feature_error("feature_unavailable", "账号功能不可用。")

    try:
        import importlib

        try:
            module = importlib.import_module(backend_module)
        except ModuleNotFoundError:
            if getattr(sys, "frozen", False):
                raise
            import importlib.util

            module_name = f"_onlineworker_account_feature_{feature_id.replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(module_name, backend_path)
            if spec is None or spec.loader is None:
                raise ImportError("missing loader")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        handler = getattr(module, "handle_account_feature")
        result = handler(action=action, payload=payload, context=trusted_context)
        return {"ok": True, "data": result, "error": None}
    except Exception:
        return _account_feature_error(
            "action_failed", "账号功能操作失败。", retryable=True
        )


def _run_account_feature_worker() -> int:
    discovered = False
    while True:
        raw = sys.stdin.buffer.readline(_ACCOUNT_FEATURE_MAX_INPUT + 2)
        if not raw:
            return 0
        if len(raw) > _ACCOUNT_FEATURE_MAX_INPUT + 1 or not raw.endswith(b"\n"):
            _print_account_feature_envelope(
                _account_feature_error("invalid_request", "账号功能请求无效。"),
                newline=True,
            )
            return 0
        try:
            request = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            request = None
        request_id = request.get("requestId") if isinstance(request, dict) else None
        if (
            not isinstance(request, dict)
            or not isinstance(request_id, str)
            or not request_id
            or len(request_id) > 128
        ):
            _print_account_feature_envelope(
                _account_feature_error("invalid_request", "账号功能请求无效。"),
                newline=True,
            )
            continue
        command = request.get("command")
        if command == "list":
            response = _account_feature_list_envelope()
            discovered = True
        elif command == "action":
            if not discovered:
                _account_feature_list_envelope()
                discovered = True
            response = _account_feature_action_envelope(
                request.get("featureId") if isinstance(request.get("featureId"), str) else "",
                request.get("action") if isinstance(request.get("action"), str) else "",
                request,
                discover=False,
            )
        else:
            response = _account_feature_error("invalid_request", "账号功能请求无效。")
        _print_account_feature_envelope(response, request_id=request_id, newline=True)


def _run_account_feature_bootstrap(argv: list[str]) -> int:
    if "--account-feature-worker" in argv:
        return _run_account_feature_worker()
    if "--account-feature-list" in argv:
        _print_account_feature_envelope(_account_feature_list_envelope())
        return 0

    feature_id = _account_feature_arg(argv, "--account-feature-id")
    action = _account_feature_arg(argv, "--account-feature-action-name")
    request = _read_account_feature_request()
    if request is None:
        _print_account_feature_envelope(
            _account_feature_error("invalid_request", "账号功能请求无效。")
        )
        return 0
    _print_account_feature_envelope(
        _account_feature_action_envelope(feature_id, action, request, discover=True)
    )
    return 0


if __name__ == "__main__" and any(flag in sys.argv[1:] for flag in _ACCOUNT_FEATURE_FLAGS):
    raise SystemExit(_run_account_feature_bootstrap(sys.argv[1:]))

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
from core.im_routes import ImRouteStore
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
_TELEGRAM_BOT_URL_RE = re.compile(r"(https://api\.telegram\.org/bot)[^/\s]+")


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _TELEGRAM_BOT_URL_RE.sub(
            r"\1<redacted>",
            super().format(record),
        )

# 持有文件锁的文件对象，进程退出时 OS 自动释放
_lock_fh = None
_main_event_loop: asyncio.AbstractEventLoop | None = None


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


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    global _main_event_loop
    if _main_event_loop is not None and not _main_event_loop.is_closed():
        return _main_event_loop
    try:
        _main_event_loop = asyncio.get_running_loop()
    except RuntimeError:
        _main_event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_main_event_loop)
    return _main_event_loop


def _telegram_httpx_kwargs(cfg) -> dict:
    kwargs = {"trust_env": bool(getattr(cfg, "telegram_trust_env", True))}
    proxy_url = str(getattr(cfg, "telegram_proxy_url", "") or "").strip()
    if proxy_url:
        kwargs["proxy"] = proxy_url
    return kwargs


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
    text: str | None = None,
    attachments: list[dict] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    usage_plugin_id: str | None = None,
    usage_source_id: str | None = None,
    usage_timezone: str | None = None,
    usage_force_refresh: bool = False,
) -> int:
    from core.provider_session_bridge import (
        archive_provider_session,
        list_provider_session_rows,
        read_provider_session_rows,
        send_provider_session_message,
    )

    normalized_operation = str(operation or "").strip().lower()
    if normalized_operation == "usage-source":
        from core.usage.runtime import get_usage_source_summary

        _print_provider_session_bridge_result(
            get_usage_source_summary(
                str(usage_plugin_id or "").strip(),
                str(usage_source_id or "").strip(),
                str(start_date or "").strip(),
                str(end_date or "").strip(),
                timezone=str(usage_timezone or "local"),
                force_refresh=bool(usage_force_refresh),
            )
        )
        return 0

    if normalized_operation == "usage-catalog":
        from core.usage.registry import get_usage_source_catalog
        _print_provider_session_bridge_result(get_usage_source_catalog())
        return 0

    normalized_provider = str(provider_id or "").strip()
    if not normalized_provider:
        raise ValueError("provider_id is required")

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
                workspace_dir=workspace_dir,
            )
        )
        return 0

    if normalized_operation == "send":
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("session_id is required for send operation")
        normalized_text = str(text or "").strip()
        if not normalized_text and not attachments:
            raise ValueError("text or attachments are required for send operation")
        asyncio.run(
            send_provider_session_message(
                normalized_provider,
                normalized_session_id,
                normalized_text,
                workspace_dir=workspace_dir,
                attachments=attachments or [],
            )
        )
        _print_provider_session_bridge_result({"ok": True})
        return 0

    if normalized_operation == "archive":
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise ValueError("session_id is required for archive operation")
        asyncio.run(
            archive_provider_session(
                normalized_provider,
                normalized_session_id,
                workspace_dir=workspace_dir,
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
        "--claude-hook-managed",
        action="store_true",
        help="Allow Claude hook bridge relay to wait for OnlineWorker-managed interaction decisions",
    )
    parser.add_argument(
        "--codex-hook-bridge",
        action="store_true",
        help="Run once as Codex hook bridge relay and exit",
    )
    parser.add_argument(
        "--codex-notify-bridge",
        action="store_true",
        help="Run once as Codex notify relay and exit",
    )
    parser.add_argument(
        "--codex-tui-host",
        action="store_true",
        help="Run a visible single-owner Codex TUI host and exit when Codex exits",
    )
    parser.add_argument(
        "--ow-codex",
        action="store_true",
        help="Run Codex CLI through OnlineWorker's local remote proxy",
    )
    parser.add_argument(
        "--ow-claude",
        action="store_true",
        help="Run Claude CLI through OnlineWorker's local HTTP proxy",
    )
    parser.add_argument("--codex-tui-target", default=None)
    parser.add_argument("--codex-tui-cd", default=None)
    parser.add_argument("--codex-tui-remote", default=None)
    parser.add_argument("--codex-tui-bin", default="codex")
    parser.add_argument("--codex-tui-extra-arg", action="append", default=[])
    parser.add_argument(
        "--provider-session-bridge",
        action="store_true",
        help="Run once as provider session bridge and exit",
    )
    parser.add_argument("--provider-id", default=None)
    parser.add_argument("--provider-session-op", default=None)
    parser.add_argument("--provider-session-id", default=None)
    parser.add_argument("--provider-workspace-dir", default=None)
    parser.add_argument("--provider-start-date", default=None)
    parser.add_argument("--provider-end-date", default=None)
    parser.add_argument("--usage-plugin-id", default=None)
    parser.add_argument("--usage-source-id", default=None)
    parser.add_argument("--usage-timezone", default="local")
    parser.add_argument("--usage-force-refresh", action="store_true")
    parser.add_argument("--provider-limit", type=int, default=50)
    args, unknown_args = parser.parse_known_args()

    data_dir = args.data_dir or default_data_dir()
    set_data_dir(data_dir)

    if args.claude_hook_bridge:
        from plugins.providers.builtin.claude.python.hook_bridge import run_claude_hook_bridge_once

        raise SystemExit(run_claude_hook_bridge_once(data_dir, managed_interactions=args.claude_hook_managed))
    if args.codex_hook_bridge:
        from plugins.providers.builtin.codex.python.hook_bridge import run_codex_hook_bridge_once

        raise SystemExit(run_codex_hook_bridge_once(data_dir))
    if args.codex_notify_bridge:
        from plugins.providers.builtin.codex.python.hook_bridge import run_codex_notify_bridge_once

        raw_payload = unknown_args[-1] if unknown_args else ""
        raise SystemExit(run_codex_notify_bridge_once(data_dir, raw_payload))
    if args.codex_tui_host:
        from plugins.providers.builtin.codex.python.tui_host_runtime import run_codex_tui_host_once

        if not args.codex_tui_cd:
            raise SystemExit("--codex-tui-cd is required")
        raise SystemExit(
            asyncio.run(
                run_codex_tui_host_once(
                    data_dir=data_dir,
                    cwd=args.codex_tui_cd,
                    target=args.codex_tui_target,
                    remote_url=args.codex_tui_remote,
                    codex_bin=args.codex_tui_bin,
                    extra_args=args.codex_tui_extra_arg,
                )
            )
        )
    if args.ow_codex:
        from plugins.providers.builtin.codex.python.cli_wrapper import run_ow_codex_once

        raise SystemExit(
            asyncio.run(
                run_ow_codex_once(
                    unknown_args,
                    data_dir=data_dir,
                )
            )
        )
    if args.ow_claude:
        from plugins.providers.builtin.claude.python.cli_wrapper import parse_ow_claude_args, run_ow_claude_from_args

        raise SystemExit(
            asyncio.run(
                run_ow_claude_from_args(
                    parse_ow_claude_args(
                        [
                            "--data-dir",
                            data_dir,
                            *unknown_args,
                        ]
                    )
                )
            )
        )
    if args.provider_session_bridge:
        raise SystemExit(
            _run_provider_session_bridge(
                args.provider_id,
                args.provider_session_op,
                session_id=args.provider_session_id,
                workspace_dir=args.provider_workspace_dir,
                limit=args.provider_limit,
                start_date=args.provider_start_date,
                end_date=args.provider_end_date,
                usage_plugin_id=args.usage_plugin_id,
                usage_source_id=args.usage_source_id,
                usage_timezone=args.usage_timezone,
                usage_force_refresh=args.usage_force_refresh,
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
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # 清除已有 handler（防止崩溃重启后重复添加）
    root_logger.handlers.clear()

    log_formatter = _RedactingFormatter(log_format)

    # RotatingFileHandler: 10MB per file, keep 3 backups
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)

    # 同时输出到 stdout（方便 launchd 抓取和调试）
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)
    root_logger.addHandler(stream_handler)

    rapid_crashes = 0
    last_crash_time = 0.0

    while True:
        try:
            storage = load_storage()
            state = AppState(storage=storage, config=cfg)

            whitelist = WhitelistFilter(allowed_user_id=cfg.allowed_user_id)
            gid = cfg.group_chat_id

            im_route_store = ImRouteStore()
            im_route_store.migrate_telegram_json_topics(storage, gid)
            state.set_im_route_store(im_route_store, gid)
            telegram_httpx_kwargs = _telegram_httpx_kwargs(cfg)

            app = (
                Application.builder()
                .token(cfg.telegram_token)
                .request(
                    HTTPXRequest(
                        read_timeout=20,
                        write_timeout=20,
                        connect_timeout=10,
                        httpx_kwargs=telegram_httpx_kwargs,
                    )
                )
                .get_updates_request(
                    HTTPXRequest(
                        read_timeout=20,
                        write_timeout=20,
                        connect_timeout=10,
                        httpx_kwargs=telegram_httpx_kwargs,
                    )
                )
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
            _get_or_create_event_loop().run_until_complete(lifecycle.pre_telegram_init(app))

            logger.info(f"onlineWorker 启动，允许用户 ID：{cfg.allowed_user_id}，群组 ID：{gid}")
            # 外层有崩溃重试循环，不能让 PTB 在每次失败后关闭当前事件循环。
            app.run_polling(
                drop_pending_updates=True,
                close_loop=False,
                allowed_updates=["message", "callback_query"],
                bootstrap_retries=-1,
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
