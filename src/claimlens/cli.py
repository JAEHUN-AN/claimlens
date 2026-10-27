"""CLI: uv run claimlens read <sample-folder> [--variant photo|clean]."""

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any

from pydantic import ValidationError

from claimlens.checks import all_passed, check_kr_bill
from claimlens.reader import read_sample


def receipt_checks(envelope: dict[str, Any]) -> list[dict[str, Any]] | None:
    docs = envelope["result"].get("documents", [])
    bills = [(i, d["kr_bill"]) for i, d in enumerate(docs) if d.get("kr_bill")]
    if not bills:
        return None
    out = []
    for i, bill in bills:
        checks = check_kr_bill(bill)
        out.append(
            {
                "document": i,
                "all_passed": all_passed(checks),
                "checks": [asdict(c) for c in checks],
            }
        )
    return out


def cmd_read(args: argparse.Namespace) -> int:
    try:
        envelope = read_sample(args.sample, args.variant)
    except (FileNotFoundError, RuntimeError, LookupError, ValidationError) as exc:
        print(f"claimlens: {exc}", file=sys.stderr)
        return 1
    envelope["receipt_checks"] = receipt_checks(envelope)
    print(json.dumps(envelope, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claimlens")
    sub = parser.add_subparsers(dest="command", required=True)
    read = sub.add_parser("read", help="Read the receipt and certificate of a sample folder.")
    read.add_argument("sample", help="Sample folder, e.g. samples/A_niseko_wrist.")
    read.add_argument("--variant", choices=["photo", "clean"], default="photo")
    read.set_defaults(func=cmd_read)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
