"""Live double-read gate eval (41c): two fresh reads, verify, compare, stop.

Runs the real gate over the hard and normal sets: every read is a fresh
live call (unique cache tags in a temp cache dir; the committed cache/
is never touched). Default prints the plan only. --execute runs it and
writes one JSON data file for `claimlens headline`, aborting past
--max-cost with partial results.
"""

import json
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claimlens import hard_eval
from claimlens.hard_eval import BASE_EST, REREAD_EST, cache_dir_scope

TAG_PREFIX = ".gate41c"


def default_provider_factory() -> Callable[[], Any]:
    from claimlens.providers.meta import MetaProvider

    def make() -> Any:
        return MetaProvider(live=True)

    return make


def _verify_final(reading: dict[str, Any], image: Path,
                  provider: Any, calls: list[dict]) -> tuple[dict[str, Any], bool]:
    """Verified final reading + stopped flag (every receipt)."""
    from claimlens.checks import all_passed, receipt_checks
    from claimlens.verify import verify_receipt

    final = reading
    stopped = False
    if reading.get("documents"):
        receipt = reading["documents"][0]
        first = receipt_checks(receipt)
        if not all_passed(first):
            seen = len(provider.calls)
            verified = verify_receipt(receipt, image, provider)
            calls += [vars(c) for c in provider.calls[seen:]]
            rest = reading.get("documents", [])[1:]
            final = {"documents": [verified["receipt"], *rest]}
            stopped = verified["status"] == "needs_manual_check"
    return final, stopped


def run_pair(case: dict[str, Any], round_no: int,
             provider_factory: Callable[[], Any]) -> dict[str, Any]:
    """One gate pair: two fresh reads, verify, compare; never a wrong pass."""
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.reader import reading_schema

    images = case["images"]
    truth = case["truth"]
    unreadable = case["unreadable"]
    finals = []
    stopped_each = []
    calls: list[dict] = []
    tags = []
    for side in ("a", "b"):
        tag = f"{TAG_PREFIX}-r{round_no}{side}-{case['key']}"
        tags.append(tag)
        provider = provider_factory()
        seen = len(provider.calls)
        reading = provider.read_documents(images, READING_INSTRUCTIONS,
                                          reading_schema(), cache_tag=tag)
        calls += [vars(c) for c in provider.calls[seen:]]
        final, stopped = _verify_final(reading, images[0], provider, calls)
        finals.append(final)
        stopped_each.append(stopped)
    values = [hard_eval.field_values(final) for final in finals]
    agree = hard_eval._gate_agree(values[0], values[1])
    if agree:
        stopped = stopped_each[0]
        wrong_fields = [] if stopped else hard_eval.wrong_numeric_fields(
            truth, finals[0], unreadable)
        reached = 0 if stopped else len(wrong_fields)
    else:
        stopped, reached, wrong_fields = True, 0, []
    case_id = {k: case[k] for k in ("sample", "transform", "variant") if k in case}
    return {"round": round_no, "case": case_id, "tags": tags, "agree": agree,
            "stopped": stopped, "stopped_each": stopped_each, "reached": reached,
            "wrong_fields": wrong_fields, "values": values, "calls": calls}


def _call_cost(calls: list[dict]) -> float:
    return hard_eval._call_cost(calls)


def execute(plans: dict[str, dict[str, Any]], repeat: int, max_cost: float,
            provider_factory: Callable[[], Any], out_dir: Path) -> dict[str, Any]:
    """Run every planned pair; aborts past max_cost with partial results."""
    results: dict[str, Any] = {"tool": "gate-eval", "repeat": repeat, "sets": {},
                               "spent": 0.0, "aborted": False,
                               "cache_before": hard_eval.git_cache_status()}
    with tempfile.TemporaryDirectory(prefix="gate-eval-") as tmp, cache_dir_scope(Path(tmp)):
        for name, plan in plans.items():
            pairs = []
            for case in plan["cases"]:
                for round_no in range(1, repeat + 1):
                    record = run_pair(case, round_no, provider_factory)
                    pairs.append(record)
                    results["spent"] += _call_cost(record["calls"])
                    if results["spent"] > max_cost:
                        results["aborted"] = True
                        break
                if results["aborted"]:
                    break
            stops = sum(p["stopped"] for p in pairs)
            leaks = sum(p["reached"] for p in pairs)
            spent = sum(_call_cost(p["calls"]) for p in pairs)
            results["sets"][name] = {
                "pairs": len(pairs), "stops": stops, "leaks": leaks,
                "spent": round(spent, 6),
                "per_claim": round(spent / len(pairs), 6) if pairs else 0.0,
                "cases": [
                    {k: case[k] for k in ("sample", "transform", "variant")
                     if k in case}
                    for case in plan["cases"]
                ],
                "pair_details": pairs,
            }
            if results["aborted"]:
                break
    results["spent"] = round(results["spent"], 6)
    results["cache_after"] = hard_eval.git_cache_status()
    results["recorded_at"] = datetime.now(UTC).isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"gate_live_{stamp}.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    results["path"] = str(path)
    return results


def estimate_text(name: str, cases: int, repeat: int) -> str:
    pairs = cases * repeat
    reads = pairs * 2
    verify_max = pairs * 2
    return (f"{name}: {cases} cases x{repeat} = {pairs} pairs, "
            f"{reads} reads + up to {verify_max} verify re-reads; "
            f"estimate ${reads * BASE_EST:.2f}-${reads * BASE_EST + verify_max * REREAD_EST:.2f}.")


def format_summary(results: dict[str, Any]) -> str:
    lines = []
    for name, summary in results["sets"].items():
        lines.append(f"{name}: {summary['pairs']} pairs, {summary['stops']} stops, "
                     f"{summary['leaks']} wrong numbers left, "
                     f"${summary['per_claim']:.4f} per claim.")
    lines.append(f"spent ${results['spent']:.4f}"
                 + (" (ABORTED past --max-cost; partial)" if results["aborted"] else ""))
    lines.append(f"cache/ before: {results['cache_before']}")
    lines.append(f"cache/ after: {results['cache_after']}")
    return "\n".join(lines)
