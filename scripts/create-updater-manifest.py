#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def signing_key_id(encoded: str, packet_size: int) -> bytes:
    lines = base64.b64decode(encoded.strip(), validate=True).decode("utf-8").splitlines()
    if len(lines) < 2 or not lines[0].startswith("untrusted comment:"):
        raise ValueError("Invalid updater signing metadata")
    packet = base64.b64decode(lines[1], validate=True)
    if len(packet) != packet_size:
        raise ValueError("Invalid updater signing packet")
    return packet[2:10]


def build_manifest(version: str, tag: str, repo: str, artifacts: Path, public_key: str) -> dict:
    if tag.removeprefix("v") != version:
        raise ValueError("Release tag does not match VERSION")
    key_id = signing_key_id(public_key, 42)
    platforms = {}
    for arch, platform in [("arm64", "darwin-aarch64"), ("x86_64", "darwin-x86_64")]:
        name = f"OnlineWorker_{version}_{arch}.app.tar.gz"
        archive = artifacts / name
        signature_file = artifacts / (name + ".sig")
        if not archive.is_file() or not archive.stat().st_size or not signature_file.is_file():
            raise ValueError(f"Missing updater package or signature for {platform}")
        signature = signature_file.read_text(encoding="utf-8").strip()
        # Catch a CI key mismatch before publishing; the app verifies the full signature on download.
        if signing_key_id(signature, 74) != key_id:
            raise ValueError(f"Updater signing key does not match the app public key: {platform}")
        platforms[platform] = {
            "url": f"https://github.com/{repo}/releases/download/{quote(tag, safe='')}/{quote(name, safe='')}",
            "signature": signature,
        }
    return {"version": version, "notes": f"OnlineWorker {version}",
            "pub_date": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "platforms": platforms}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a complete signed Tauri updater manifest.")
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    config = json.loads((ROOT / "mac-app/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    result = build_manifest(version, args.tag, args.repo, args.artifacts, config["plugins"]["updater"]["pubkey"])
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("Created updater manifest with both macOS architectures")


if __name__ == "__main__":
    main()
