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
from claimlens.hard_eval import BASE_EST, PROBE_EST, REREAD_EST, cache_dir_scope

TAG_PREFIX = ".gate41c"

UNSEEN_VARIANTS = ("photo", "clean")


def load_unseen_scenarios(unseen_dir: Path) -> dict[str, Any]:
    """Unseen truth keyed by case id (truth.json, scenarios.json shape)."""
    truth = json.loads((unseen_dir / "truth.json").read_text(encoding="utf-8"))
    return {s["id"]: s for s in truth["scenarios"]}


def plan_unseen(unseen_dir: Path,
                samples: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Unseen plan: every wanted case in photo + clean; probed at run time."""
    ids = sorted(load_unseen_scenarios(unseen_dir))
    if samples:
        ids = [s for s in ids if s in samples]
    cases = [{"sample": sid, "variant": variant}
             for sid in ids for variant in UNSEEN_VARIANTS]
    return {"cases": cases}


def load_trip_cases(trips_dir: Path) -> dict[str, Any]:
    """Trips truth keyed by case id (trips/truth.json)."""
    truth = json.loads((trips_dir / "truth.json").read_text(encoding="utf-8"))
    return {c["id"]: c for c in truth["cases"]}


def plan_trips(trips_dir: Path,
               samples: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Trips plan: every receipt/cert pair in photo + clean; probed at run time.

    Each case lists its pairs so multi-receipt trips (T1, T5) and the
    certificate-less trip (T4, one page) run through the same gate.
    """
    by_id = load_trip_cases(trips_dir)
    ids = sorted(by_id)
    if samples:
        ids = [s for s in ids if s in samples]
    cases = []
    for sid in ids:
        for receipt_file, cert_file in by_id[sid]["pairs"]:
            for variant in UNSEEN_VARIANTS:
                cases.append({"sample": sid, "variant": variant,
                              "receipt_file": receipt_file,
                              "cert_file": cert_file,
                              "pages": 1 if cert_file is None else 2})
    return {"cases": cases}


def trip_pair_scenario(case: dict[str, Any], receipt_file: str,
                       cert_file: str | None) -> dict[str, Any]:
    """A gate pair's truth in scenarios.json shape for ground_truth."""
    docs = {d["file"]: d for d in case["documents"]}
    receipt = docs[receipt_file]["data"]
    cert = docs[cert_file]["data"] if cert_file else {"diagnoses": []}
    return {
        "id": case["id"],
        "expected": {"currency": case["currency"], "total": receipt["total"]},
        "documents": [
            {"doc_type": "receipt", "data": {"items": receipt["items"]}},
            {"doc_type": "medical_certificate",
             "data": {"diagnoses": cert["diagnoses"]}},
        ],
        "patient": case["patient"],
    }


def resolve_trip_images(case_dir: Path, receipt_file: str,
                        cert_file: str | None, variant: str) -> list[Path]:
    """Receipt plus certificate (receipt alone when no certificate exists)."""
    images = []
    for stem in [receipt_file] + ([cert_file] if cert_file else []):
        matches = sorted(case_dir.glob(f"{stem}_{variant}.*"))
        if not matches:
            raise FileNotFoundError(f"No {stem}_{variant} image in {case_dir}")
        images.append(matches[0])
    return images


def default_provider_factory() -> Callable[[], Any]:
    from claimlens.providers.meta import MetaProvider

    def make() -> Any:
        return MetaProvider(live=True)

    return make


def _verify_final(reading: dict[str, Any], image: Path,
                  provider: Any, calls: list[dict], pos: int = 0,
                  ) -> tuple[dict[str, Any], bool]:
    """Verified final reading + stopped flag (every receipt)."""
    from claimlens.checks import all_passed, receipt_checks
    from claimlens.verify import REREAD_READ2_TAG, verify_receipt

    final = reading
    stopped = False
    if reading.get("documents"):
        receipt = reading["documents"][0]
        first = receipt_checks(receipt)
        if not all_passed(first):
            seen = len(provider.calls)
            tag = "" if pos == 0 else REREAD_READ2_TAG
            verified = verify_receipt(receipt, image, provider, cache_tag=tag)
            calls += [vars(c) for c in provider.calls[seen:]]
            rest = reading.get("documents", [])[1:]
            final = {"documents": [verified["receipt"], *rest]}
            stopped = verified["status"] == "needs_manual_check"
    return final, stopped


def run_pair(case: dict[str, Any], round_no: int,
             provider_factory: Callable[[], Any],
             probe_pages: bool = False) -> dict[str, Any]:
    """One gate pair: two fresh reads, verify, compare; never a wrong pass.

    With probe_pages, turned pages are rotated upright once and both
    reads use the upright copy. Probe failures read as is and are noted.
    """
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.reader import reading_schema

    truth = case["truth"]
    unreadable = case["unreadable"]
    finals = []
    stopped_each = []
    calls: list[dict] = []
    tags = []
    rot_notes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="upright-") as tmp:
        images = case["images"]
        if probe_pages:
            from claimlens.rotation import FAILED_NOTE, upright_pages

            prover = provider_factory()
            seen = len(prover.calls)
            images, rot_notes = upright_pages(images, prover, Path(tmp))
            calls += [vars(c) for c in prover.calls[seen:]]
            if FAILED_NOTE in rot_notes:
                # C4: no orientation, no reads; the pair stops for a person.
                case_id = {k: case[k] for k in ("sample", "transform", "variant",
                                               "receipt_file", "cert_file")
                           if k in case}
                return {"round": round_no, "case": case_id, "tags": [],
                        "agree": False, "stopped": True, "stopped_each": [],
                        "reached": 0, "wrong_fields": [], "values": [],
                        "calls": calls, "rotation": rot_notes}
        for pos, side in enumerate(("a", "b")):
            tag = f"{TAG_PREFIX}-r{round_no}{side}-{case['key']}"
            tags.append(tag)
            provider = provider_factory()
            seen = len(provider.calls)
            reading = provider.read_documents(images, READING_INSTRUCTIONS,
                                              reading_schema(), cache_tag=tag)
            calls += [vars(c) for c in provider.calls[seen:]]
            final, stopped = _verify_final(reading, images[0], provider,
                                           calls, pos=pos)
            finals.append(final)
            stopped_each.append(stopped)
    values = [hard_eval.field_values(final) for final in finals]
    agree = hard_eval._gate_agree(values[0], values[1])
    if agree:
        # Same rule as serve: either read failing its verify stops the claim.
        stopped = any(stopped_each)
        wrong_fields = [] if stopped else hard_eval.wrong_numeric_fields(
            truth, finals[0], unreadable)
        reached = 0 if stopped else len(wrong_fields)
    else:
        stopped, reached, wrong_fields = True, 0, []
    case_id = {k: case[k] for k in ("sample", "transform", "variant",
                                               "receipt_file", "cert_file")
               if k in case}
    return {"round": round_no, "case": case_id, "tags": tags, "agree": agree,
            "stopped": stopped, "stopped_each": stopped_each, "reached": reached,
            "wrong_fields": wrong_fields, "values": values, "calls": calls,
            "rotation": rot_notes}


def _call_cost(calls: list[dict]) -> float:
    return hard_eval._call_cost(calls)


def execute(plans: dict[str, dict[str, Any]], repeat: int, max_cost: float,
            provider_factory: Callable[[], Any], out_dir: Path) -> dict[str, Any]:
    """Run every planned pair; aborts past max_cost with partial results."""
    results: dict[str, Any] = {"tool": "gate-eval", "repeat": repeat, "sets": {},
                               "fields": list(hard_eval.GATE_FIELDS),
                               "spent": 0.0, "aborted": False,
                               "cache_before": hard_eval.git_cache_status()}
    with tempfile.TemporaryDirectory(prefix="gate-eval-") as tmp, cache_dir_scope(Path(tmp)):
        for name, plan in plans.items():
            pairs = []
            for case in plan["cases"]:
                for round_no in range(1, repeat + 1):
                    record = run_pair(case, round_no, provider_factory,
                                      probe_pages=plan.get("probe", name == "hard"))
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
                    {k: case[k] for k in ("sample", "transform", "variant",
                                         "receipt_file", "cert_file")
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


def estimate_text(name: str, cases: int, repeat: int,
                  probes_per_pair: int = 0,
                  probes_total: int | None = None) -> str:
    """Plan line; probes_total overrides it when pairs vary (trips' T4)."""
    pairs = cases * repeat
    reads = pairs * 2
    verify_max = pairs * 2
    probes = pairs * probes_per_pair if probes_total is None else probes_total
    lo = reads * BASE_EST + probes * PROBE_EST
    parts = f"{reads} reads + up to {verify_max} verify re-reads"
    if probes:
        parts += f" + {probes} rotation probes"
    return (f"{name}: {cases} cases x{repeat} = {pairs} pairs, {parts}; "
            f"estimate ${lo:.2f}-${lo + verify_max * REREAD_EST:.2f}.")


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
