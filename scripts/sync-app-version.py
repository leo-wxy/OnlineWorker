#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
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
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync OnlineWorker app packaging versions.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="OnlineWorker repository root",
    )
    args = parser.parse_args()
    version = sync_versions(args.root.resolve())
    print(f"Synced app version: {version}")


if __name__ == "__main__":
    main()
