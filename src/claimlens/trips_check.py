"""Per-case serve-path scenario checks for the real trips (49b).

Each trip runs through the real upload boundary (serve.route_post, no
sockets): the natural upload for the situation — every receipt plus the
certificate — with the traveller's panel facts. Nothing here reads
accuracy; gate-eval --set trips does that. This checks the path: the
upload verdict, the stop badge, and the questions asked.

One-image (T4) and three-image (T1, T5) trips take the multi path (50):
per-photo reads merged with provenance, or the certificate question
when no certificate is uploaded. With the engine down the traveller
trips pause at engine_unreachable on correct reads; with the engine up
the same trips decide, and both outcomes pass (56) — the record says
which side it was. A live model may stop earlier (blocked,
needs_manual_check), which still passes with a note. Trips that must
never decide (T4 without a certificate, T6 dental) fail on any
decision badge either way.
"""

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from claimlens import gate_eval
from claimlens.hard_eval import BASE_EST, PROBE_EST, REREAD_EST

TRIPS_DIR = Path("samples") / "unseen" / "trips"

CONSISTENCY_EST = REREAD_EST  # one text-only Spark pass; priced as a re-read
STOP_BADGES = {"needs_review", "blocked", "needs_manual_check"}
# 56: the engine's own decision vocabulary (serve reports output["decision"]
# verbatim; the demo template mirrors this list in JS). A trip whose truth
# accepts these decides when the engine is up — and that passes too.
DECISION_BADGES = ("PAID", "PARTIAL", "DENIED", "HUMAN_REVIEW")

PORT = 8000
HEADERS = {"host": f"127.0.0.1:{PORT}", "content_type": "application/json"}


def scenario_uploads(case: dict[str, Any], case_dir: Path) -> list[Path]:
    """The trip's natural photo upload: every receipt plus the certificate."""
    return [case_dir / f"{doc['file']}_photo.jpg" for doc in case["documents"]]


def plan_case(case: dict[str, Any]) -> dict[str, Any]:
    """Offline facts for one case: upload verdict, eligibility, estimate."""
    from claimlens.eval import country_of_currency
    from claimlens.serve import missing_facts, resolve_eligibility

    images = [d for d in case["documents"] if d["role"] != "certificate"]
    certs = [d for d in case["documents"] if d["role"] == "certificate"]
    upload_n = len(images) + len(certs)
    person = case["person"]
    missing = missing_facts(person)
    country = country_of_currency(case["currency"])
    eligibility = [resolve_eligibility(person, {"country": country})["outcome"]]
    # the 2-image path reads both pages in one call per side; the multi
    # path reads each photo separately.
    reads = 2 if upload_n == 2 else 2 * upload_n
    probes = upload_n
    rereads = 2 * len(images)
    probe_noun = "probe" if probes == 1 else "probes"
    if certs and images and len(images) <= 5 and len(certs) <= 1:
        lo = reads * BASE_EST + probes * PROBE_EST + CONSISTENCY_EST
        hi = lo + rereads * REREAD_EST
        calls = (f"{reads} reads + {probes} {probe_noun} + 1 consistency + "
                 f"up to {rereads} verify re-reads")
    else:
        lo = reads * BASE_EST + probes * PROBE_EST
        hi = lo
        calls = (f"{reads} reads + {probes} {probe_noun} "
                 "(stops before verify: no certificate to merge with)")
    return {
        "id": case["id"], "uploads": upload_n, "missing_facts": missing,
        "eligibility": eligibility, "live": True,
        "calls": calls,
        "estimate": (round(lo, 4), round(hi, 4)),
        "expected": case["expected"]["serve_today"],
        "accept_up": list(case["expected"].get("serve_engine_up", {}).get(
            "badges", [])),
    }


def plan(cases: list[str] | None = None) -> dict[str, Any]:
    """Whole-set plan: per-case facts plus totals. No model calls."""
    by_id = gate_eval.load_trip_cases(TRIPS_DIR)
    ids = sorted(by_id) if not cases else list(cases)
    unknown = [c for c in ids if c not in by_id]
    if unknown:
        raise ValueError(f"unknown trips case: {', '.join(unknown)}")
    rows = [plan_case(by_id[cid]) for cid in ids]
    lo = round(sum(r["estimate"][0] for r in rows), 4)
    hi = round(sum(r["estimate"][1] for r in rows), 4)
    return {"cases": rows, "estimate": (lo, hi)}


def format_plan(summary: dict[str, Any]) -> str:
    """Human-readable plan with the call counts and the cost bracket."""
    lines = ["Trips serve-path scenario check (no network calls made):",
             "each trip through the real upload boundary, photo images;",
             "committed cache/ stays untouched."]
    for row in summary["cases"]:
        exp = row["expected"]
        want = exp["badge"] if exp["status"] == 200 else exp["reason"]
        noun = "upload" if row["uploads"] == 1 else "uploads"
        accept_up = row.get("accept_up") or []
        engine_note = ("; engine up also accepts a decision badge"
                       if accept_up else "; never decided")
        lines.append(f"{row['id']}: {row['uploads']} {noun}, facts "
                     f"{'complete' if not row['missing_facts'] else row['missing_facts']}, "
                     f"eligibility {','.join(row['eligibility'])}; "
                     f"{row['calls']}; expect {exp['status']} {want}{engine_note}.")
    lo, hi = summary["estimate"]
    lines.append(f"TOTAL live calls across {len(summary['cases'])} trips; "
                 f"estimate ${lo:.2f}-${hi:.2f}.")
    lines.append("Stopped before any API call. Re-run with --execute to run it.")
    return "\n".join(lines)


def run_case(case_id: str) -> dict[str, Any]:
    """One trip through route_post; the response plus the raw outcome."""
    from claimlens import serve
    from claimlens.serve import route_post

    by_id = gate_eval.load_trip_cases(TRIPS_DIR)
    case = by_id[case_id]
    case_dir = TRIPS_DIR / case_id
    images = []
    for path in scenario_uploads(case, case_dir):
        images.append({"name": path.name,
                       "data": base64.b64encode(path.read_bytes()).decode("ascii")})
    body = json.dumps({"images": images, "person": case["person"],
                       "scenario": None}).encode("utf-8")
    status, payload = route_post("/api/run", body, len(body), dict(HEADERS), PORT)
    result = payload.get("result", {}) if status == 200 else {}
    return {
        "case": case_id, "uploads": len(images), "status": status,
        "badge": result.get("badge", ""), "title": result.get("title", ""),
        "questions": payload.get("questions", []) if status == 200 else [],
        "cost_usd": payload.get("cost_usd", 0.0) if status == 200 else 0.0,
        "error": payload.get("error", "") if status != 200 else "",
        "engine_up": bool(serve.neo4j_up()),
    }


def judge(record: dict[str, Any], expected: dict[str, Any],
          engine_up_badges: tuple[str, ...] | list[str] = ()) -> dict[str, Any]:
    """Pass/fail against serve_today; earlier stops pass with a note.

    56: engine_up_badges (from truth serve_engine_up) also pass — the
    same trip pauses at engine_unreachable with the engine down and
    decides with it up. Trips that must never decide pass an empty set.
    """
    if record["status"] != expected["status"]:
        return {"verdict": "FAIL",
                "note": f"status {record['status']}, want {expected['status']}"}
    if expected["status"] != 200:
        want = expected.get("reason", "")
        if want and want in record["error"]:
            return {"verdict": "PASS", "note": record["error"]}
        return {"verdict": "FAIL", "note": f"error {record['error']!r}, want {want!r}"}
    if record["badge"] == expected["badge"]:
        return {"verdict": "PASS", "note": ""}
    if record["badge"] in engine_up_badges:
        return {"verdict": "PASS (decided, engine up)",
                "note": f"badge {record['badge']}, engine-down want "
                        f"{expected['badge']}"}
    if record["badge"] in STOP_BADGES:
        return {"verdict": "PASS (earlier stop)",
                "note": f"badge {record['badge']}, want {expected['badge']}"}
    return {"verdict": "FAIL",
            "note": f"badge {record['badge']}, want {expected['badge']}"}


def execute(cases: list[str] | None = None, max_cost: float = 1.0,
            out_dir: Path = Path("out")) -> dict[str, Any]:
    """Run every trip; aborts past max_cost with partial results."""
    from claimlens.hard_eval import cache_dir_scope, git_cache_status

    by_id = gate_eval.load_trip_cases(TRIPS_DIR)
    ids = sorted(by_id) if not cases else list(cases)
    results: dict[str, Any] = {"tool": "trips-check", "cases": [], "spent": 0.0,
                               "aborted": False,
                               "cache_before": git_cache_status()}
    with TemporaryDirectory(prefix="trips-check-") as tmp, cache_dir_scope(Path(tmp)):
        for cid in ids:
            record = run_case(cid)
            want = by_id[cid]["expected"]
            up_badges = want.get("serve_engine_up", {}).get("badges", [])
            record.update(judge(record, want["serve_today"], up_badges))
            results["cases"].append(record)
            results["spent"] += record["cost_usd"]
            if results["spent"] > max_cost:
                results["aborted"] = True
                break
    results["spent"] = round(results["spent"], 6)
    results["cache_after"] = git_cache_status()
    results["recorded_at"] = datetime.now(UTC).isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"trips_check_{stamp}.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    results["path"] = str(path)
    return results


def format_results(results: dict[str, Any]) -> str:
    """Per-case verdict table for the execute run."""
    lines = []
    for record in results["cases"]:
        engine = {True: "engine up", False: "engine down"}.get(
            record.get("engine_up"), "engine unknown")
        if record["status"] == 200:
            what = (f"{record['status']} {record['badge']} "
                    f"({len(record['questions'])} questions, "
                    f"${record['cost_usd']:.4f}, {engine})")
        else:
            what = f"{record['status']} {record['error']} ({engine})"
        note = f" — {record['note']}" if record["note"] else ""
        lines.append(f"{record['case']}: {record['verdict']}: {what}{note}")
    lines.append(f"spent ${results['spent']:.4f}"
                 + (" (aborted past max-cost)" if results["aborted"] else "")
                 + f"; wrote {results['path']}")
    return "\n".join(lines)
