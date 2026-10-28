#!/usr/bin/env python3
"""One entry point for the demo-video recorders.

Usage:
    uv run python tools/video/record.py main|vertical [--dry-run] [--music FILE]
    uv run python tools/video/record.py main|vertical --post-only [--music FILE]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import record_main
import record_vertical


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ("main", "vertical"):
        print("usage: record.py main|vertical [--dry-run] [--music FILE] ...",
              file=sys.stderr)
        return 2
    cut, rest = args[0], args[1:]
    module = record_main if cut == "main" else record_vertical
    return module.main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
