from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from plugins.providers.builtin.codex.python.account_store import atomic_write, operation_lock


class SessionAssetError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _index_entries(home: Path) -> list[dict[str, Any]]:
    path = home / "session_index.jsonl"
    if not path.exists() or path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            entries.append(value)
    return entries


def _rollouts(home: Path):
    for location in ("sessions", "archived_sessions"):
        root = home / location
        if not root.is_dir() or root.is_symlink():
            continue
        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            dirs[:] = [name for name in dirs if not (current_path / name).is_symlink()]
            for name in files:
                path = current_path / name
                if name.endswith(".jsonl") and not path.is_symlink() and path.is_file():
                    resolved = path.resolve()
                    if resolved.is_relative_to(home):
                        yield location, resolved


def _scan_rollout(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as stream:
            first = json.loads(stream.readline())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(first, dict) or first.get("type") != "session_meta":
        return None
    payload = first.get("payload") if isinstance(first.get("payload"), dict) else {}
    session_id = payload.get("id") or first.get("id")
    if not isinstance(session_id, str) or not session_id:
        return None
    return {
        "sessionId": session_id,
        "cwd": str(payload.get("cwd") or ""),
        "createdAt": payload.get("timestamp") or first.get("timestamp"),
        "source": payload.get("source") or payload.get("thread_source") or "",
    }


def _session_kind(title: str, cwd: str, source: object) -> str:
    source_text = json.dumps(source, ensure_ascii=False) if isinstance(source, (dict, list)) else str(source)
    text = f"{title}\n{cwd}\n{source_text}".casefold()
    if any(value in text for value in ("subagent", "sub-agent", "agent run")):
        return "subagent"
    if any(value in text for value in ("external", "imported", "cli run")):
        return "external"
    return "conversation"


def _usage_for_file(path: Path, cutoff: datetime, seen: set[tuple]) -> dict[str, int]:
    totals = {"inputTokens": 0, "cachedInputTokens": 0, "outputTokens": 0, "reasoningTokens": 0, "totalTokens": 0}
    previous: dict[str, int] | None = None
    try:
        stream = path.open("r", encoding="utf-8", errors="ignore")
    except OSError:
        return totals
    with stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") != "event_msg" or _timestamp(row.get("timestamp")) is None or _timestamp(row.get("timestamp")) < cutoff:
                continue
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            info = payload.get("info") if payload.get("type") == "token_count" and isinstance(payload.get("info"), dict) else {}
            last = info.get("last_token_usage") if isinstance(info.get("last_token_usage"), dict) else None
            cumulative = info.get("total_token_usage") if isinstance(info.get("total_token_usage"), dict) else None
            current = last
            if current is None and cumulative is not None:
                current = {key: max(0, int(cumulative.get(key, 0)) - int((previous or {}).get(key, 0))) for key in cumulative}
            if cumulative is not None:
                previous = {key: int(value) for key, value in cumulative.items() if isinstance(value, (int, float))}
            if current is None:
                continue
            values = (
                int(current.get("input_tokens", 0)),
                int(current.get("cached_input_tokens", 0)),
                int(current.get("output_tokens", 0)),
                int(current.get("reasoning_output_tokens", 0)),
                int(current.get("total_tokens", 0)),
            )
            signature = (row.get("timestamp"), str(info.get("model") or ""), *values)
            if signature in seen:
                continue
            seen.add(signature)
            for key, value in zip(totals, values, strict=True):
                totals[key] += max(0, value)
    return totals


def list_sessions(home: Path, *, query: str = "", include_usage: bool = True, kind: str = "conversation") -> dict[str, object]:
    if kind not in {"conversation", "external", "subagent", "all"}:
        raise SessionAssetError("invalid_session_kind")
    home = home.resolve()
    titles = {entry["id"]: str(entry.get("thread_name") or entry.get("title") or "") for entry in _index_entries(home)}
    cutoff = datetime.now(UTC) - timedelta(days=30)
    seen_usage: set[tuple] = set()
    rows: list[dict[str, object]] = []
    summary = {"inputTokens": 0, "cachedInputTokens": 0, "outputTokens": 0, "reasoningTokens": 0, "totalTokens": 0}
    for location, path in _rollouts(home):
        meta = _scan_rollout(path)
        if meta is None:
            continue
        title = titles.get(meta["sessionId"]) or Path(meta["cwd"]).name or meta["sessionId"]
        session_kind = _session_kind(title, str(meta["cwd"]), meta.pop("source", ""))
        if kind != "all" and session_kind != kind:
            continue
        if query and query.casefold() not in f"{title}\n{meta['cwd']}".casefold():
            continue
        usage = _usage_for_file(path, cutoff, seen_usage) if include_usage else {}
        for key, value in usage.items():
            summary[key] += value
        updated = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat().replace("+00:00", "Z")
        rows.append({
            **meta,
            "title": title,
            "updatedAt": updated,
            "location": location,
            "state": "archived" if location == "archived_sessions" else "current",
            "sessionKind": session_kind,
            "tokenSummary": usage or None,
            "relativeRolloutPath": path.relative_to(home).as_posix(),
        })
    rows.sort(key=lambda item: str(item["updatedAt"]), reverse=True)
    return {"sessions": rows, "usage30d": {**summary, "cost": {"status": "unavailable"}}}


def _write_index(home: Path, entries: list[dict[str, Any]]) -> None:
    path = home / "session_index.jsonl"
    raw = b"".join(json.dumps(entry, ensure_ascii=False, separators=(",", ":")).encode() + b"\n" for entry in entries)
    atomic_write(path, raw)


def trash_sessions(plugin_root: Path, home: Path, session_ids: list[str]) -> dict[str, object]:
    with operation_lock(plugin_root):
        listed = list_sessions(home, include_usage=False, kind="all")["sessions"]
        by_id = {item["sessionId"]: item for item in listed if item["sessionId"] in session_ids}
        index = _index_entries(home)
        old_index = (home / "session_index.jsonl").read_bytes() if (home / "session_index.jsonl").exists() else None
        package = plugin_root / "session-trash" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        package.mkdir(parents=True, mode=0o700)
        moved: list[tuple[Path, Path]] = []
        manifest_items: list[dict[str, object]] = []
        try:
            for session_id in dict.fromkeys(session_ids):
                item = by_id.get(session_id)
                if item is None:
                    continue
                source = (home / str(item["relativeRolloutPath"])).resolve()
                if not source.is_relative_to(home) or source.is_symlink():
                    raise SessionAssetError("unsafe_session_path")
                target = package / f"{hashlib.sha256(session_id.encode()).hexdigest()}.jsonl"
                entry = next((value for value in index if value.get("id") == session_id), None)
                manifest_items.append({
                    "session_id": session_id,
                    "title": item["title"],
                    "cwd": item.get("cwd"),
                    "original_relative_path": item["relativeRolloutPath"],
                    "session_index_entry": entry,
                    "mtime_ns": source.stat().st_mtime_ns,
                    "trash_file": target.name,
                })
            if not manifest_items:
                package.rmdir()
                return {"trashed": [], "count": 0}
            atomic_write(package / "manifest.json", json.dumps({"version": 1, "sessions": manifest_items}, ensure_ascii=False, indent=2).encode())
            for item in manifest_items:
                source = home / str(item["original_relative_path"])
                target = package / str(item["trash_file"])
                os.replace(source, target)
                moved.append((source, target))
            trashed_ids = {item["session_id"] for item in manifest_items}
            _write_index(home, [entry for entry in index if entry.get("id") not in trashed_ids])
            return {"trashed": [item["session_id"] for item in manifest_items], "count": len(manifest_items)}
        except Exception as exc:
            for source, target in reversed(moved):
                if target.exists() and not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, source)
            if old_index is None:
                (home / "session_index.jsonl").unlink(missing_ok=True)
            else:
                atomic_write(home / "session_index.jsonl", old_index)
            shutil.rmtree(package, ignore_errors=True)
            raise SessionAssetError("trash_failed") from exc


def list_trash(plugin_root: Path) -> list[dict[str, object]]:
    root = plugin_root / "session-trash"
    results: list[dict[str, object]] = []
    if not root.exists():
        return results
    for manifest_path in root.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in manifest.get("sessions", []):
            if isinstance(item, dict):
                mtime_ns = item.get("mtime_ns")
                updated_at = datetime.fromtimestamp(mtime_ns / 1_000_000_000, UTC).isoformat().replace("+00:00", "Z") if isinstance(mtime_ns, int) else None
                results.append({
                    "sessionId": item.get("session_id"),
                    "title": item.get("title") or item.get("session_id"),
                    "cwd": item.get("cwd") or "",
                    "updatedAt": updated_at,
                    "sessionKind": "conversation",
                    "state": "trashed",
                    "trashPackage": manifest_path.parent.name,
                })
    return results


def restore_sessions(plugin_root: Path, home: Path, session_ids: list[str]) -> dict[str, object]:
    with operation_lock(plugin_root):
        home = home.resolve()
        root = plugin_root / "session-trash"
        if root.is_symlink():
            raise SessionAssetError("unsafe_session_path")
        index = _index_entries(home)
        old_index = (home / "session_index.jsonl").read_bytes() if (home / "session_index.jsonl").exists() else None
        requested = set(session_ids)
        restored: list[str] = []
        manifests: list[tuple[Path, bytes, dict[str, Any], list[object]]] = []
        planned: list[tuple[Path, Path, int, str, object]] = []
        moved: list[tuple[Path, Path]] = []
        try:
            root_resolved = root.resolve()
            planned_targets: set[Path] = set()
            for manifest_path in root.glob("*/manifest.json"):
                package = manifest_path.parent
                if manifest_path.is_symlink() or package.is_symlink() or package.resolve().parent != root_resolved:
                    raise SessionAssetError("unsafe_session_path")
                manifest_raw = manifest_path.read_bytes()
                manifest = json.loads(manifest_raw)
                items = manifest.get("sessions")
                if not isinstance(items, list):
                    raise SessionAssetError("restore_failed")
                remaining: list[object] = []
                for item in items:
                    session_id = item.get("session_id") if isinstance(item, dict) else None
                    if session_id not in requested:
                        remaining.append(item)
                        continue
                    expected_name = f"{hashlib.sha256(session_id.encode()).hexdigest()}.jsonl"
                    if item.get("trash_file") != expected_name:
                        raise SessionAssetError("unsafe_session_path")
                    candidate = package / expected_name
                    source = candidate.resolve()
                    target = (home / str(item.get("original_relative_path", ""))).resolve()
                    if candidate.is_symlink() or not candidate.is_file() or source.parent != package.resolve() or not target.is_relative_to(home):
                        raise SessionAssetError("unsafe_session_path")
                    if target.exists() or target in planned_targets:
                        remaining.append(item)
                        continue
                    meta = _scan_rollout(candidate)
                    if meta is None or meta["sessionId"] != session_id:
                        raise SessionAssetError("identity_mismatch")
                    mtime_ns = int(item.get("mtime_ns", -1))
                    if mtime_ns < 0:
                        raise SessionAssetError("restore_failed")
                    planned.append((candidate, target, mtime_ns, session_id, item.get("session_index_entry")))
                    planned_targets.add(target)
                if len(remaining) != len(items):
                    manifests.append((manifest_path, manifest_raw, manifest, remaining))

            if not planned:
                return {"restored": [], "count": 0}
            for source, target, mtime_ns, session_id, entry in planned:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                moved.append((source, target))
                os.utime(target, ns=(mtime_ns, mtime_ns))
                if isinstance(entry, dict) and not any(value.get("id") == session_id for value in index):
                    index.append(entry)
                restored.append(session_id)
            for manifest_path, _raw, manifest, remaining in manifests:
                if remaining:
                    manifest["sessions"] = remaining
                    atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode())
                else:
                    manifest_path.unlink(missing_ok=True)
            _write_index(home, index)
        except Exception as exc:
            for source, target in reversed(moved):
                if target.exists() and not source.exists():
                    os.replace(target, source)
            for manifest_path, manifest_raw, _manifest, _remaining in manifests:
                atomic_write(manifest_path, manifest_raw)
            if old_index is None:
                (home / "session_index.jsonl").unlink(missing_ok=True)
            else:
                atomic_write(home / "session_index.jsonl", old_index)
            if isinstance(exc, SessionAssetError):
                raise
            raise SessionAssetError("restore_failed") from exc
        for manifest_path, _raw, _manifest, remaining in manifests:
            if not remaining:
                try:
                    manifest_path.parent.rmdir()
                except OSError:
                    pass
        return {"restored": restored, "count": len(restored)}


def _provider(home: Path) -> str:
    path = home / "config.toml"
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return "openai"
    provider = value.get("model_provider")
    return provider.strip() if isinstance(provider, str) and provider.strip() else "openai"


def repair_visibility(home: Path) -> dict[str, int | str]:
    home = home.resolve()
    provider = _provider(home)
    rows_changed = 0
    rollouts_changed = 0
    for db_path in (home / "state_5.sqlite", home / "sqlite" / "state_5.sqlite"):
        if not db_path.exists() or db_path.is_symlink():
            continue
        connection = sqlite3.connect(db_path)
        backups: dict[Path, tuple[bytes, int, int]] = {}
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
            if not {"id", "model_provider", "rollout_path"}.issubset(columns):
                connection.close()
                continue
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT id, model_provider, rollout_path FROM threads").fetchall()
            for _session_id, current, raw_path in rows:
                if current != provider:
                    connection.execute("UPDATE threads SET model_provider = ? WHERE id = ?", (provider, _session_id))
                    rows_changed += 1
                if not isinstance(raw_path, str) or not raw_path:
                    continue
                path = Path(raw_path)
                path = path.resolve() if path.is_absolute() else (home / path).resolve()
                if not path.is_relative_to(home) or not path.exists() or path.is_symlink() or path in backups:
                    continue
                raw = path.read_bytes()
                lines = raw.splitlines(keepends=True)
                if not lines:
                    continue
                first = json.loads(lines[0])
                if first.get("type") != "session_meta" or not isinstance(first.get("payload"), dict):
                    continue
                if first["payload"].get("model_provider") == provider:
                    continue
                stat = path.stat()
                backups[path] = (raw, stat.st_mode & 0o777, stat.st_mtime_ns)
                first["payload"]["model_provider"] = provider
                newline = b"\n" if lines[0].endswith(b"\n") else b""
                lines[0] = json.dumps(first, ensure_ascii=False, separators=(",", ":")).encode() + newline
                atomic_write(path, b"".join(lines))
                os.chmod(path, stat.st_mode & 0o777)
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                rollouts_changed += 1
            connection.commit()
        except Exception as exc:
            connection.rollback()
            for path, (raw, mode, mtime_ns) in backups.items():
                atomic_write(path, raw)
                os.chmod(path, mode)
                os.utime(path, ns=(mtime_ns, mtime_ns))
            raise SessionAssetError("repair_failed") from exc
        finally:
            connection.close()
    return {"provider": provider, "rowsChanged": rows_changed, "rolloutsChanged": rollouts_changed}
