#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path


VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def read_version(root: Path) -> str:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise SystemExit(f"Invalid VERSION value: {version!r}")
    return version


def update_json_version(path: Path, version: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def update_cargo_version(path: Path, version: str) -> None:
    source = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        source,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"Cannot find package version in {path}")
    path.write_text(updated, encoding="utf-8")


def sync_versions(root: Path) -> str:
    version = read_version(root)
    update_json_version(root / "mac-app/package.json", version)
    update_cargo_version(root / "mac-app/src-tauri/Cargo.toml", version)
    update_json_version(root / "mac-app/src-tauri/tauri.conf.json", version)
    lock_path = root / "mac-app/src-tauri/Cargo.lock"
    if lock_path.exists():
        source = lock_path.read_text(encoding="utf-8")
        source, count = re.subn(r'(\[\[package\]\]\nname = "onlineworker-app"\nversion = ")[^"]+(")',
                                lambda match: match[1] + version + match[2], source, count=1)
        if count != 1:
            raise SystemExit("Cannot find onlineworker-app in Cargo.lock")
        lock_path.write_text(source, encoding="utf-8")
    return version


def check_versions(root: Path, tag: str | None = None) -> str:
    version = read_version(root)
    versions = {
        "package.json": json.loads((root / "mac-app/package.json").read_text())["version"],
        "Cargo.toml": tomllib.loads((root / "mac-app/src-tauri/Cargo.toml").read_text())["package"]["version"],
        "tauri.conf.json": json.loads((root / "mac-app/src-tauri/tauri.conf.json").read_text())["version"],
    }
    lock_path = root / "mac-app/src-tauri/Cargo.lock"
    if lock_path.exists():
        package = next(entry for entry in tomllib.loads(lock_path.read_text())["package"] if entry["name"] == "onlineworker-app")
        versions["Cargo.lock"] = package["version"]
    if tag is not None:
        versions["tag"] = tag.removeprefix("v")
    if any(value != version for value in versions.values()):
        raise SystemExit(f"Packaging versions must match VERSION {version}: {versions}")
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync OnlineWorker app packaging versions.")
    parser.add_argument("--check", action="store_true", help="Check versions without writing files")
    parser.add_argument("--tag", help="Require the release tag to match VERSION")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="OnlineWorker repository root",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    version = check_versions(root, args.tag) if args.check else sync_versions(root)
    print(f"{'Checked' if args.check else 'Synced'} app version: {version}")


if __name__ == "__main__":
    main()
