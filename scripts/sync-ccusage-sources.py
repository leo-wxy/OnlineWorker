#!/usr/bin/env python3
"""Print ccusage's built-in agent IDs from the pinned Rust source."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOADER = (
    ROOT / "third_party/ccusage/rust/crates/ccusage/src/adapter/all/loader.rs"
)
CONSTANT_PATTERN = re.compile(
    r"\bBUILT_IN_AGENT_NAMES\s*:\s*&\s*\[\s*&str\s*\]\s*=\s*&\s*\[(?P<body>.*?)\]\s*;",
    re.DOTALL,
)
RUST_STRING_PATTERN = re.compile(r'"(?P<value>(?:\\.|[^"\\])*)"')
CANONICAL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class SourceExtractionError(ValueError):
    """Raised when the pinned Rust source does not match the expected contract."""


def extract_agent_ids(source: str) -> list[str]:
    match = CONSTANT_PATTERN.search(source)
    if match is None:
        raise SourceExtractionError("BUILT_IN_AGENT_NAMES constant was not found")

    values = [
        json.loads(f'"{item.group("value")}"')
        for item in RUST_STRING_PATTERN.finditer(match.group("body"))
    ]
    if not values:
        raise SourceExtractionError("BUILT_IN_AGENT_NAMES contains no agent IDs")

    invalid = [value for value in values if not CANONICAL_ID_PATTERN.fullmatch(value)]
    if invalid:
        raise SourceExtractionError(
            f"BUILT_IN_AGENT_NAMES contains non-canonical IDs: {', '.join(invalid)}"
        )
    if len(values) != len(set(values)):
        raise SourceExtractionError("BUILT_IN_AGENT_NAMES contains duplicate agent IDs")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract canonical built-in agent IDs from ccusage loader.rs"
    )
    parser.add_argument(
        "--loader",
        type=Path,
        default=DEFAULT_LOADER,
        help=f"path to loader.rs (default: {DEFAULT_LOADER})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        source = args.loader.read_text(encoding="utf-8")
        agent_ids = extract_agent_ids(source)
    except (OSError, UnicodeError, SourceExtractionError, json.JSONDecodeError) as error:
        print(
            f"error: cannot extract ccusage agent IDs from {args.loader}: {error}",
            file=sys.stderr,
        )
        return 1

    print("\n".join(agent_ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
