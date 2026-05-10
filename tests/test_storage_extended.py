# tests/test_storage_extended.py
"""
测试 core/storage.py 的文件扫描逻辑。
使用 tmp_path fixture 创建真实临时文件结构，无需 mock。
"""
import json
import os
import pytest
from plugins.providers.builtin.codex.python import storage_runtime as storage_module
from plugins.providers.builtin.codex.python.storage_runtime import scan_codex_session_cwds


def write_jsonl(path: str, first_line: dict, extra: str = ""):
    """写一个 .jsonl 文件，首行为 JSON，后续可追加任意内容。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(first_line) + "\n")
        if extra:
            f.write(extra + "\n")


class TestScanCodexSessionCwds:
    def test_nonexistent_dir_returns_empty(self, tmp_path):
        result = scan_codex_session_cwds(str(tmp_path / "nonexistent"))
        assert result == []

    def test_empty_dir_returns_empty(self, tmp_path):
        result = scan_codex_session_cwds(str(tmp_path))
        assert result == []

    def test_single_valid_session(self, tmp_path):
        cwd = "/home/user/project"
        write_jsonl(
            str(tmp_path / "rollout-20240101-abc.jsonl"),
            {"type": "session_meta", "payload": {"cwd": cwd}},
        )
        result = scan_codex_session_cwds(str(tmp_path))
        assert len(result) == 1
        assert result[0]["path"] == cwd
        assert result[0]["name"] == "project"
        assert result[0]["thread_count"] == 1

    def test_multiple_sessions_same_cwd(self, tmp_path):
        cwd = "/home/user/project"
        for i in range(3):
            write_jsonl(
                str(tmp_path / f"rollout-{i}.jsonl"),
                {"type": "session_meta", "payload": {"cwd": cwd}},
            )
        result = scan_codex_session_cwds(str(tmp_path))
        assert len(result) == 1
        assert result[0]["thread_count"] == 3

    def test_subagent_sessions_do_not_increase_thread_count(self, tmp_path):
        cwd = "/home/user/project"
        write_jsonl(
            str(tmp_path / "rollout-main.jsonl"),
            {"type": "session_meta", "payload": {"cwd": cwd, "source": "cli"}},
        )
        write_jsonl(
            str(tmp_path / "rollout-subagent.jsonl"),
            {
                "type": "session_meta",
                "payload": {
                    "cwd": cwd,
                    "source": {
                        "subagent": {
                            "thread_spawn": {
                                "parent_thread_id": "tid-parent",
                                "depth": 1,
                            }
                        }
                    },
                },
            },
        )
        result = scan_codex_session_cwds(str(tmp_path))
        assert len(result) == 1
        assert result[0]["thread_count"] == 1

    def test_multiple_cwds(self, tmp_path):
        cwds = ["/project/a", "/project/b", "/project/c"]
        for i, cwd in enumerate(cwds):
            write_jsonl(
                str(tmp_path / f"rollout-{i}.jsonl"),
                {"type": "session_meta", "payload": {"cwd": cwd}},
            )
        result = scan_codex_session_cwds(str(tmp_path))
        assert len(result) == 3
        paths = {r["path"] for r in result}
        assert paths == set(cwds)

    def test_wrong_type_skipped(self, tmp_path):
        write_jsonl(
            str(tmp_path / "rollout-bad.jsonl"),
            {"type": "something_else", "payload": {"cwd": "/home/user/project"}},
        )
        result = scan_codex_session_cwds(str(tmp_path))
        assert result == []

    def test_relative_cwd_skipped(self, tmp_path):
        write_jsonl(
            str(tmp_path / "rollout-rel.jsonl"),
            {"type": "session_meta", "payload": {"cwd": "relative/path"}},
        )
        result = scan_codex_session_cwds(str(tmp_path))
        assert result == []

    def test_corrupt_jsonl_skipped(self, tmp_path):
        fpath = str(tmp_path / "corrupt.jsonl")
        with open(fpath, "w") as f:
            f.write("not valid json\n")
        result = scan_codex_session_cwds(str(tmp_path))
        assert result == []

    def test_empty_jsonl_skipped(self, tmp_path):
        fpath = str(tmp_path / "empty.jsonl")
        open(fpath, "w").close()
        result = scan_codex_session_cwds(str(tmp_path))
        assert result == []

    def test_non_jsonl_files_skipped(self, tmp_path):
        fpath = str(tmp_path / "session.txt")
        with open(fpath, "w") as f:
            f.write(json.dumps({"type": "session_meta", "payload": {"cwd": "/x"}}) + "\n")
        result = scan_codex_session_cwds(str(tmp_path))
        assert result == []

    def test_sorted_by_thread_count_descending(self, tmp_path):
        # cwd_a: 3 threads, cwd_b: 1 thread
        for i in range(3):
            write_jsonl(
                str(tmp_path / f"a-{i}.jsonl"),
                {"type": "session_meta", "payload": {"cwd": "/project/a"}},
            )
        write_jsonl(
            str(tmp_path / "b-0.jsonl"),
            {"type": "session_meta", "payload": {"cwd": "/project/b"}},
        )
        result = scan_codex_session_cwds(str(tmp_path))
        assert result[0]["path"] == "/project/a"
        assert result[0]["thread_count"] == 3


class TestListCodexSessionMetaThreadsByCwd:
    def test_lists_jsonl_only_main_threads_with_preview_and_created_time(self, tmp_path):
        cwd = "/Users/example/Projects/onlineWorker"
        session_path = tmp_path / "2026" / "04" / "10" / "rollout-2026-04-10T17-27-11-tid-phase15.jsonl"
        write_jsonl(
            str(session_path),
            {
                "timestamp": "2026-04-10T09:27:23.213Z",
                "type": "session_meta",
                "payload": {
                    "id": "tid-phase15",
                    "timestamp": "2026-04-10T09:27:11.147Z",
                    "cwd": cwd,
                    "source": "cli",
                },
            },
            extra=json.dumps(
                {
                    "timestamp": "2026-04-10T09:27:30.000Z",
                    "type": "response_item",
                    "payload": {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "继续处理phase15"},
                        ],
                    },
                },
                ensure_ascii=False,
            ),
        )

        result = storage_module.list_codex_session_meta_threads_by_cwd(
            cwd,
            sessions_dir=str(tmp_path),
            limit=20,
        )

        assert [item["id"] for item in result] == ["tid-phase15"]
        assert result[0]["preview"] == "继续处理phase15"
        assert result[0]["createdAt"] == 1775813231147
        assert result[0]["updatedAt"] == 1775813231147

    def test_skips_subagent_sessions(self, tmp_path):
        cwd = "/Users/example/Projects/onlineWorker"
        write_jsonl(
            str(tmp_path / "rollout-main.jsonl"),
            {
                "type": "session_meta",
                "payload": {
                    "id": "tid-main",
                    "timestamp": "2026-04-10T09:27:11.147Z",
                    "cwd": cwd,
                    "source": "cli",
                },
            },
            extra=json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "主线程"},
                        ],
                    },
                },
                ensure_ascii=False,
            ),
        )
        write_jsonl(
            str(tmp_path / "rollout-subagent.jsonl"),
            {
                "type": "session_meta",
                "payload": {
                    "id": "tid-subagent",
                    "timestamp": "2026-04-10T09:28:11.147Z",
                    "cwd": cwd,
                    "source": {
                        "subagent": {
                            "thread_spawn": {
                                "parent_thread_id": "tid-main",
                                "depth": 1,
                            }
                        }
                    },
                },
            },
            extra=json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "subagent"},
                        ],
                    },
                },
                ensure_ascii=False,
            ),
        )

        result = storage_module.list_codex_session_meta_threads_by_cwd(
            cwd,
            sessions_dir=str(tmp_path),
            limit=20,
        )

        assert [item["id"] for item in result] == ["tid-main"]
