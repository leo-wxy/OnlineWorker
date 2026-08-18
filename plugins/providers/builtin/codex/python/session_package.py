from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from plugins.providers.builtin.codex.python.account_store import atomic_write
from plugins.providers.builtin.codex.python.session_assets import SessionAssetError, _index_entries, _scan_rollout, _write_index, list_sessions


KIND = "codex-session-export"
VERSION = 1
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ENTRY_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILES = 1000


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ":" not in name and all(part not in {"", ".", ".."} for part in path.parts)


def _safe_rollout(name: object) -> str:
    if not isinstance(name, str) or not _safe_member(name):
        raise SessionAssetError("invalid_package_path")
    path = PurePosixPath(name)
    if path.parts[0] not in {"sessions", "archived_sessions"} or not path.name.startswith("rollout-") or path.suffix != ".jsonl":
        raise SessionAssetError("invalid_package_path")
    return name


def export_sessions(home: Path, session_ids: list[str], destination: str | Path) -> dict[str, object]:
    home = home.resolve()
    target = Path(destination)
    if target.is_symlink():
        raise SessionAssetError("unsafe_export_path")
    target = target.parent.resolve() / target.name
    rows = {item["sessionId"]: item for item in list_sessions(home, include_usage=False, kind="all")["sessions"]}
    index = {entry["id"]: entry for entry in _index_entries(home)}
    manifest_items: list[dict[str, object]] = []
    sources: list[tuple[Path, str]] = []
    for position, session_id in enumerate(session_ids):
        row = rows.get(session_id)
        if row is None:
            continue
        source = (home / str(row["relativeRolloutPath"])).resolve()
        if not source.is_relative_to(home) or source.is_symlink():
            raise SessionAssetError("unsafe_session_path")
        raw = source.read_bytes()
        entry = f"files/{position:04d}-{hashlib.sha256(session_id.encode()).hexdigest()[:12]}/rollout.jsonl"
        manifest_items.append({
            "session_id": session_id,
            "title": row["title"],
            "cwd": row["cwd"],
            "updated_at": row["updatedAt"],
            "relative_rollout_path": row["relativeRolloutPath"],
            "file_entry": entry,
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "session_index_entry": index.get(session_id),
            "source_instance": "onlineworker",
        })
        sources.append((source, entry))
    if not manifest_items:
        raise SessionAssetError("empty_selection")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(fd)
    tmp = Path(raw_tmp)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps({"kind": KIND, "package_version": VERSION, "exported_at": datetime.now(UTC).isoformat(), "sessions": manifest_items}, ensure_ascii=False, indent=2))
            for source, entry in sources:
                archive.write(source, entry)
        os.chmod(tmp, 0o600)
        with tmp.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(tmp, target)
        os.chmod(target, 0o600)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return {"fileName": target.name, "count": len(manifest_items), "sizeBytes": target.stat().st_size}


def import_sessions(home: Path, archive_path: str | Path) -> dict[str, object]:
    home = home.resolve()
    source = Path(archive_path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_ARCHIVE_BYTES:
        raise SessionAssetError("invalid_package")
    existing = {item["sessionId"]: item for item in list_sessions(home, include_usage=False, kind="all")["sessions"]}
    old_index = (home / "session_index.jsonl").read_bytes() if (home / "session_index.jsonl").exists() else None
    index = _index_entries(home)
    written: list[Path] = []
    results: list[dict[str, str]] = []
    try:
        with zipfile.ZipFile(source) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES or sum(info.file_size for info in infos) > MAX_TOTAL_BYTES or any(not _safe_member(info.filename) or info.file_size > MAX_ENTRY_BYTES or stat.S_ISLNK(info.external_attr >> 16) for info in infos):
                raise SessionAssetError("invalid_package")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("kind") != KIND or manifest.get("package_version") != VERSION or not isinstance(manifest.get("sessions"), list):
                raise SessionAssetError("unsupported_package")
            for item in manifest["sessions"]:
                if not isinstance(item, dict) or not isinstance(item.get("session_id"), str):
                    raise SessionAssetError("invalid_package")
                file_entry = item.get("file_entry")
                relative = _safe_rollout(item.get("relative_rollout_path"))
                if not isinstance(file_entry, str) or not file_entry.startswith("files/") or not file_entry.endswith(".jsonl") or not _safe_member(file_entry):
                    raise SessionAssetError("invalid_package_path")
                raw = archive.read(file_entry)
                digest = hashlib.sha256(raw).hexdigest()
                if len(raw) != item.get("size_bytes") or digest != item.get("sha256") or len(digest) != 64:
                    raise SessionAssetError("integrity_failed")
                meta = _scan_rollout_bytes(raw)
                if meta != item["session_id"]:
                    raise SessionAssetError("identity_mismatch")
                session_id = item["session_id"]
                current = existing.get(session_id)
                if current:
                    current_hash = hashlib.sha256((home / str(current["relativeRolloutPath"])).read_bytes()).hexdigest()
                    status_value = "skipped" if current_hash == item["sha256"] else "conflict"
                    results.append({"sessionId": session_id, "status": status_value})
                    continue
                target = (home / relative).resolve()
                if not target.is_relative_to(home) or target.exists() or target.is_symlink():
                    results.append({"sessionId": session_id, "status": "conflict"})
                    continue
                atomic_write(target, raw)
                written.append(target)
                entry = item.get("session_index_entry")
                if isinstance(entry, dict) and not any(value.get("id") == session_id for value in index):
                    index.append(entry)
                results.append({"sessionId": session_id, "status": "imported"})
        _write_index(home, index)
        return {"items": results, "imported": sum(item["status"] == "imported" for item in results)}
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        if old_index is None:
            (home / "session_index.jsonl").unlink(missing_ok=True)
        else:
            atomic_write(home / "session_index.jsonl", old_index)
        raise


def _scan_rollout_bytes(raw: bytes) -> str | None:
    try:
        first = json.loads(raw.splitlines()[0])
    except (IndexError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    payload = first.get("payload") if isinstance(first, dict) and isinstance(first.get("payload"), dict) else {}
    value = payload.get("id") or (first.get("id") if isinstance(first, dict) else None)
    return value if isinstance(value, str) else None
