from types import SimpleNamespace

import main


class _DummyFilter:
    def __and__(self, other):
        return self

    def __rand__(self, other):
        return self

    def __invert__(self):
        return self


class _FakeApp:
    def __init__(self, run_polling_calls):
        self._run_polling_calls = run_polling_calls
        self.post_init = None
        self.post_shutdown = None
        self.error_handlers = []

    def add_handler(self, handler, group=0):
        return None

    def add_error_handler(self, handler):
        self.error_handlers.append(handler)
        return None

    def run_polling(self, **kwargs):
        self._run_polling_calls.append(kwargs)
        if len(self._run_polling_calls) == 1:
            raise RuntimeError("Timed out")
        raise KeyboardInterrupt()


class _FakeApplicationBuilder:
    def __init__(self, run_polling_calls):
        self._run_polling_calls = run_polling_calls

    def token(self, token):
        return self

    def request(self, request):
        return self

    def build(self):
        return _FakeApp(self._run_polling_calls)


def test_main_retry_path_keeps_event_loop_open(monkeypatch):
    run_polling_calls = []
    dummy_filter = _DummyFilter()

    cfg = SimpleNamespace(
        telegram_token="token",
        allowed_user_id=123,
        group_chat_id=456,
        log_level="INFO",
    )

    monkeypatch.setattr(main, "_acquire_flock", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "load_config", lambda data_dir=None: cfg)
    monkeypatch.setattr(main, "load_storage", lambda: object())
    monkeypatch.setattr(main, "AppState", lambda storage, config: SimpleNamespace())
    monkeypatch.setattr(main, "HTTPXRequest", lambda **kwargs: object())
    monkeypatch.setattr(main, "Application", SimpleNamespace(builder=lambda: _FakeApplicationBuilder(run_polling_calls)))
    monkeypatch.setattr(main, "WhitelistFilter", lambda allowed_user_id: dummy_filter)
    monkeypatch.setattr(
        main,
        "filters",
        SimpleNamespace(
            TEXT=dummy_filter,
            PHOTO=dummy_filter,
            Regex=lambda pattern: dummy_filter,
        ),
    )
    monkeypatch.setattr(main, "CommandHandler", lambda *args, **kwargs: object())
    monkeypatch.setattr(main, "MessageHandler", lambda *args, **kwargs: object())
    monkeypatch.setattr(main, "CallbackQueryHandler", lambda *args, **kwargs: object())
    monkeypatch.setattr(main, "TypeHandler", lambda *args, **kwargs: object())
    monkeypatch.setattr(main, "LifecycleManager", lambda *args, **kwargs: SimpleNamespace(post_init=None, post_shutdown=None))
    monkeypatch.setattr(main.time, "sleep", lambda *_args, **_kwargs: None)

    for factory_name in (
        "make_start_handler",
        "make_ping_handler",
        "make_echo_handler",
        "make_status_handler",
        "make_help_handler",
        "make_active_handler",
        "make_restart_handler",
        "make_stop_handler",
        "make_workspace_handler",
        "make_ws_open_callback_handler",
        "make_thread_open_callback_handler",
        "make_cli_handler",
        "make_cli_callback_handler",
        "make_new_thread_handler",
        "make_list_thread_handler",
        "make_archive_thread_handler",
        "make_skills_handler",
        "make_history_handler",
        "make_message_handler",
        "make_callback_handler",
    ):
        monkeypatch.setattr(main, factory_name, lambda *args, **kwargs: object())

    main.main()

    assert run_polling_calls == [
        {
            "drop_pending_updates": True,
            "close_loop": False,
            "allowed_updates": ["message", "callback_query"],
        },
        {
            "drop_pending_updates": True,
            "close_loop": False,
            "allowed_updates": ["message", "callback_query"],
        },
    ]
