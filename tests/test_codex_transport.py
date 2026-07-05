from plugins.providers.builtin.codex.python.transport import resolve_unix_socket_path


def test_resolve_unix_socket_path_unquotes_percent_encoded_path():
    assert resolve_unix_socket_path(
        "unix:///Users/example/Library/Application%20Support/OnlineWorker/codex.sock"
    ) == "/Users/example/Library/Application Support/OnlineWorker/codex.sock"
