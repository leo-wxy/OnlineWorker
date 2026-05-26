#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.user_messages.neutralizer import neutralize_abusive_language  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test OnlineWorker user message neutralization.")
    parser.add_argument("text", help="User message text to normalize")
    args = parser.parse_args(argv)

    result = neutralize_abusive_language(args.text)
    print(f"original: {args.text}")
    print(f"normalized: {result.text}")
    print(f"changed: {str(result.changed).lower()}")
    print("matches:")
    if not result.matches:
        print("  none")
    else:
        for match in result.matches:
            detail = f"{match.value} / {match.kind} / {match.action}"
            if match.action == "replace":
                detail += f" -> {match.replacement}"
            print(f"  - {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
