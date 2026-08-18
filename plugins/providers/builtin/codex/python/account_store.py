from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from plugins.providers.builtin.codex.python.account_model import AccountRecord, redacted_index_dto, upsert_account


class AccountStoreError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes, *, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if backup and path.exists():
            backup_path = path.with_suffix(path.suffix + ".bak")
            atomic_write(backup_path, path.read_bytes())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
        _fsync_dir(path.parent)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


_LOCKS = threading.local()


@contextmanager
def operation_lock(root: str | Path) -> Iterator[None]:
    root_path = Path(root).expanduser().resolve()
    key = str(root_path)
    held = getattr(_LOCKS, "held", {})
    if key in held:
        held[key][1] += 1
        try:
            yield
        finally:
            held[key][1] -= 1
        return
    root_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = root_path / "operation.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        held[key] = [fd, 1]
        _LOCKS.held = held
        yield
    finally:
        held.pop(key, None)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class AccountStore:
    VERSION = 1

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.accounts_dir = self.root / "accounts"
        self.key_path = self.root / "key"
        self.index_path = self.root / "index.json"

    def _key(self) -> bytes:
        if self.key_path.exists():
            key = self.key_path.read_bytes()
            if len(key) != 32:
                raise AccountStoreError("invalid_key")
            return key
        key = os.urandom(32)
        atomic_write(self.key_path, key)
        return key

    def _index(self) -> dict:
        if not self.index_path.exists():
            return {"version": self.VERSION, "accounts": []}
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AccountStoreError("invalid_index") from exc
        if value.get("version") != self.VERSION or not isinstance(value.get("accounts"), list):
            raise AccountStoreError("invalid_index")
        return value

    def _detail_path(self, account_id: str) -> Path:
        digest = hashlib.sha256(account_id.encode()).hexdigest()
        return self.accounts_dir / f"{digest}.json"

    def _encode(self, record: AccountRecord) -> bytes:
        key = self._key()
        nonce = os.urandom(12)
        payload = json.dumps(
            {
                "auth_mode": record.auth_mode,
                "identity_key": record.identity_key,
                "identity_display": record.identity_display,
                "source": record.source,
                "credentials": record.credentials,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        ciphertext = AESGCM(key).encrypt(nonce, payload, record.identity_key.encode())
        envelope = {
            "version": self.VERSION,
            "key_id": hashlib.sha256(key).hexdigest(),
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        }
        return json.dumps(envelope, separators=(",", ":")).encode()

    def _decode(self, account_id: str, raw: bytes) -> tuple[AccountRecord, bool]:
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AccountStoreError("invalid_detail") from exc
        legacy = value.get("version") is None and isinstance(value.get("credentials"), dict)
        if legacy:
            detail = value
        else:
            if value.get("version") != self.VERSION:
                raise AccountStoreError("unsupported_version")
            try:
                key = self._key()
                if value.get("key_id") != hashlib.sha256(key).hexdigest():
                    raise AccountStoreError("wrong_key")
                nonce = base64.b64decode(value["nonce"], validate=True)
                ciphertext = base64.b64decode(value["ciphertext"], validate=True)
                if len(nonce) != 12:
                    raise AccountStoreError("invalid_detail")
                plain = AESGCM(key).decrypt(nonce, ciphertext, account_id.encode())
                detail = json.loads(plain)
            except AccountStoreError:
                raise
            except (KeyError, ValueError, InvalidTag, json.JSONDecodeError) as exc:
                raise AccountStoreError("invalid_detail") from exc
        try:
            record = AccountRecord(
                auth_mode=detail["auth_mode"],
                identity_key=detail["identity_key"],
                identity_display=detail["identity_display"],
                source=detail["source"],
                credentials=deepcopy(detail["credentials"]),
            )
        except (KeyError, TypeError) as exc:
            raise AccountStoreError("invalid_detail") from exc
        if record.identity_key != account_id:
            raise AccountStoreError("identity_mismatch")
        return record, legacy

    def list_records(self) -> list[AccountRecord]:
        with operation_lock(self.root):
            records: list[AccountRecord] = []
            for item in self._index()["accounts"]:
                account_id = item.get("id")
                if not isinstance(account_id, str):
                    raise AccountStoreError("invalid_index")
                path = self._detail_path(account_id)
                raw = path.read_bytes()
                record, legacy = self._decode(account_id, raw)
                if legacy:
                    atomic_write(path, self._encode(record), backup=True)
                records.append(record)
            return records

    def get(self, account_id: str) -> AccountRecord:
        with operation_lock(self.root):
            path = self._detail_path(account_id)
            record, legacy = self._decode(account_id, path.read_bytes())
            if legacy:
                atomic_write(path, self._encode(record), backup=True)
            return record

    def list_redacted(self, current_id: str | None = None) -> list[dict[str, object]]:
        with operation_lock(self.root):
            index = self._index()
            accounts = deepcopy(index["accounts"])
            for item in accounts:
                item["isCurrent"] = item.get("id") == current_id
            return accounts

    def upsert(self, record: AccountRecord) -> str:
        with operation_lock(self.root):
            index = self._index()
            existing = next((item for item in index["accounts"] if item.get("id") == record.identity_key), None)
            if existing is not None:
                current_record, _ = self._decode(record.identity_key, self._detail_path(record.identity_key).read_bytes())
                merged = [current_record]
                result = upsert_account(merged, record)
                if result.record is None:
                    raise AccountStoreError("ambiguous_identity")
                record = result.record
            item = redacted_index_dto(record)
            if existing and isinstance(existing.get("quota"), dict):
                item["quota"] = deepcopy(existing["quota"])
            path = self._detail_path(record.identity_key)
            old_detail = path.read_bytes() if path.exists() else None
            old_index = self.index_bytes()
            try:
                atomic_write(path, self._encode(record), backup=path.exists())
                if existing is None:
                    index["accounts"].append(item)
                    status = "inserted"
                else:
                    index["accounts"][index["accounts"].index(existing)] = item
                    status = "updated"
                atomic_write(self.index_path, json.dumps(index, ensure_ascii=False, indent=2).encode(), backup=True)
                return status
            except Exception as exc:
                if old_detail is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, old_detail)
                if old_index is None:
                    self.index_path.unlink(missing_ok=True)
                else:
                    atomic_write(self.index_path, old_index)
                raise AccountStoreError("write_failed") from exc

    def set_quota(self, account_id: str, quota: dict[str, object]) -> None:
        with operation_lock(self.root):
            index = self._index()
            item = next((value for value in index["accounts"] if value.get("id") == account_id), None)
            if item is None:
                raise AccountStoreError("account_not_found")
            item["quota"] = deepcopy(quota)
            atomic_write(self.index_path, json.dumps(index, ensure_ascii=False, indent=2).encode(), backup=True)

    def index_bytes(self) -> bytes | None:
        return self.index_path.read_bytes() if self.index_path.exists() else None
