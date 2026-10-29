"""Hard-set eval: harsh variants, repeat runs, and the pipeline metrics.

`claimlens eval --set hard` runs the hard image set (see hard_images);
`--set normal --repeat N` re-runs the committed set for run-to-run
agreement. Without --execute both only print the call plan with a cost
estimate and stop before any network call.

Cache discipline: canonical hard run-1 recordings (base read plus any
re-read) go to cache/hard/ as new files; every repeat run and its
re-reads go to a scratch dir. The committed cache/ tree is only ever
read. Agreement compares per-field values across runs; accuracy scores
run 1 (plus the mean over runs). Crop-cut cells expect an honest null.
"""

import json
import os
import statistics
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claimlens import cache as replay_cache
from claimlens import eval as base_eval
from claimlens.cache import CacheMissError
from claimlens.checks import all_passed, receipt_checks
from claimlens.hard_images import ensure_hard_set
from claimlens.prompts import READING_INSTRUCTIONS
from claimlens.providers.meta import MODEL, MetaProvider
from claimlens.providers.replay import ReplayProvider
from claimlens.reader import reading_schema, resolve_sample_images
from claimlens.verify import verify_receipt

NORMAL_SAMPLES = tuple(base_eval.SAMPLE_IDS)
NORMAL_VARIANTS = tuple(base_eval.VARIANTS)

# The 10 hosted-read costs recorded in docs/eval.md; the plan prices base
# reads at their median and narrow re-reads at a stated flat allowance.
EVAL_MD_COSTS = [0.0099, 0.0090, 0.0127, 0.0107, 0.0125, 0.0102, 0.0137, 0.0135,
                 0.0171, 0.0142]
BASE_EST = statistics.median(EVAL_MD_COSTS)
REREAD_EST = 0.005

FIELDS = ("docs", "currency", "total", "lines", "amounts", "diags", "kr_cells",
          "instit", "pii")

# The re-read only touches numbers, so recovery is scored on numbers alone.
NUMERIC_FIELDS = ("total", "lines", "amounts", "kr_cells")


def hard_dir() -> Path:
    return Path(os.environ.get("CLAIMLENS_CACHE_DIR", "cache")) / "hard"


@contextmanager
def cache_dir_scope(path: Path | None):
    """Point the replay cache at path (None restores the default)."""
    old = os.environ.get("CLAIMLENS_CACHE_DIR")
    if path is None:
        os.environ.pop("CLAIMLENS_CACHE_DIR", None)
    else:
        os.environ["CLAIMLENS_CACHE_DIR"] = str(path)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("CLAIMLENS_CACHE_DIR", None)
        else:
            os.environ["CLAIMLENS_CACHE_DIR"] = old


def hard_cache_key(receipt: Path, cert: Path) -> str:
    from claimlens.providers.meta import prepare_image

    blobs = [prepare_image(receipt), prepare_image(cert)]
    return replay_cache.cache_key(blobs, READING_INSTRUCTIONS, reading_schema(), MODEL)


def _try_replay(images: list[Path]) -> tuple[dict[str, Any], list[dict]]:
    """Replay from the ambient cache dir; raises CacheMissError when absent."""
    replay = ReplayProvider()
    result = replay.read_documents(images, READING_INSTRUCTIONS, reading_schema())
    return result, [vars(c) for c in replay.calls]


def _close(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) < 0.01


def compare_hard(sample_id: str, truth: dict[str, Any], reading: dict[str, Any],
                 unreadable: dict[str, Any]) -> dict[str, Any]:
    """eval.compare plus honest-null scoring for physically cut cells."""
    metrics = base_eval.compare(sample_id, truth, reading)
    docs = reading.get("documents", [])
    receipt = docs[0] if docs else {}
    guesses = 0
    if unreadable.get("total"):
        total = receipt.get("total_amount")
        metrics["total"] = "ok" if total is None else "FAIL"
        guesses += 0 if total is None else 1
    if unreadable.get("line_amounts"):
        metrics["lines"] = "n/a (cut)"
        metrics["amounts"] = "n/a (cut)"
        guesses += sum(1 for i in receipt.get("line_items", [])
                       if i.get("amount") is not None)
    cut_cells = unreadable.get("kr_cells") or []
    if cut_cells:
        bill = receipt.get("kr_bill") or {}
        exp_cells = truth["kr_cells"] or []
        hit = 0
        for n, exp in enumerate(exp_cells, start=1):
            value = bill.get(f"cell_{n}")
            if n in cut_cells:
                hit += value is None
                guesses += value is not None
            else:
                hit += value == exp
        metrics["kr_cells"] = f"{hit}/{len(exp_cells)}"
    metrics["guesses"] = guesses
    metrics["excluded"] = ([f for f in ("lines", "amounts") if metrics.get(f) == "n/a (cut)"])
    return metrics


def field_values(reading: dict[str, Any]) -> dict[str, Any]:
    """Per-field values for run-to-run agreement (JSON shaped)."""
    docs = reading.get("documents", [])
    receipt = docs[0] if docs else {}
    cert = docs[1] if len(docs) > 1 else {}
    bill = receipt.get("kr_bill") or {}
    return {
        "docs": [d.get("doc_type") for d in docs],
        "currency": receipt.get("currency"),
        "total": receipt.get("total_amount"),
        "lines": [i.get("amount") for i in receipt.get("line_items", [])],
        "amounts": [i.get("amount") for i in receipt.get("line_items", [])],
        "diags": [d.get("code", "") for d in cert.get("diagnoses", [])],
        "kr_cells": [bill.get(f"cell_{n}") for n in range(1, 11)] if receipt.get("kr_bill") else None,
        "instit": bill.get("institution_type"),
        "pii": sorted({i.get("value", "") for d in docs for i in d.get("pii", [])}),
    }


def wrong_numeric_fields(truth: dict[str, Any], reading: dict[str, Any],
                         unreadable: dict[str, Any]) -> list[str]:
    """Names of the wrong numbers in a final reading (guesses on cut cells count)."""
    docs = reading.get("documents", [])
    receipt = docs[0] if docs else {}
    wrong: list[str] = []
    total = receipt.get("total_amount")
    if unreadable.get("total"):
        if total is not None:
            wrong.append("total")
    elif total is None or not _close(total, truth["total"]):
        wrong.append("total")
    if unreadable.get("line_amounts"):
        wrong += [f"lines[{i}]" for i, item in enumerate(receipt.get("line_items", []))
                  if item.get("amount") is not None]
    else:
        read = [float(i.get("amount", 0)) for i in receipt.get("line_items", [])]
        exp = truth["line_amounts"]
        for i in range(max(len(read), len(exp))):
            if i >= len(read) or i >= len(exp) or not _close(read[i], exp[i]):
                wrong.append(f"lines[{i}]")
    if truth["kr_cells"] is not None:
        bill = receipt.get("kr_bill") or {}
        cut = set(unreadable.get("kr_cells") or [])
        for n, exp in enumerate(truth["kr_cells"], start=1):
            value = bill.get(f"cell_{n}")
            if n in cut:
                if value is not None:
                    wrong.append(f"kr_cells[{n}]")
            elif value != exp:
                wrong.append(f"kr_cells[{n}]")
    return wrong


def _numeric_wrongs(truth: dict[str, Any], reading: dict[str, Any],
                    unreadable: dict[str, Any]) -> int:
    """Wrong numbers in a final reading (guesses on cut cells count)."""
    return len(wrong_numeric_fields(truth, reading, unreadable))


def run_once(sample_id: str, images: list[Path], truth: dict[str, Any],
             unreadable: dict[str, Any], replay_dir: Path | None, live_dir: Path,
             force_live: bool,
             provider_factory: Callable[[], Any]) -> dict[str, Any]:
    """One read plus the check/re-read pipeline; returns the run record.

    Run 1 replays from replay_dir (committed cache, or hard/ for hard
    cases) and falls back to a live call stored under live_dir; later
    runs are always live into the scratch dir. Only live calls land in
    the record's calls list, so replayed runs cost nothing.
    """
    live_calls: list[dict] = []
    result: dict[str, Any] | None = None
    provider = "replay"
    if not force_live:
        with cache_dir_scope(replay_dir):
            try:
                result, _ = _try_replay(images)
            except CacheMissError:
                result = None
    if result is None:
        with cache_dir_scope(live_dir):
            live = provider_factory()
            seen = len(live.calls)
            result = live.read_documents(images, READING_INSTRUCTIONS,
                                         reading_schema())
            live_calls += [vars(c) for c in live.calls[seen:]]
            provider = live.name
    record: dict[str, Any] = {
        "provider": provider, "calls": live_calls,
        "base": compare_hard(sample_id, truth, result, unreadable),
        "values": field_values(result),
        "base_wrongs": _numeric_wrongs(truth, result, unreadable),
    }
    receipt = result["documents"][0] if result.get("documents") else {}
    record["verify"] = None
    record["checks_first"] = None
    record["stopped"] = False
    final = result
    first = receipt_checks(receipt)
    record["checks_first"] = "pass" if all_passed(first) else "FAIL"
    if not all_passed(first):
        with cache_dir_scope(live_dir):
            verifier = provider_factory()
            seen = len(verifier.calls)
            verified = verify_receipt(receipt, images[0], verifier)
            live_calls += [vars(c) for c in verifier.calls[seen:]]
        record["verify"] = {
            "status": verified["status"],
            "corrected": verified.get("corrected", []),
        }
        rest = result.get("documents", [])[1:]
        final = {"documents": [verified["receipt"], *rest]}
        record["stopped"] = verified["status"] == "needs_manual_check"
    record["final"] = compare_hard(sample_id, truth, final, unreadable)
    record["final_values"] = field_values(final)
    wrongs = _numeric_wrongs(truth, final, unreadable)
    record["reached"] = 0 if record["stopped"] else wrongs
    record["wrong_numbers"] = wrongs
    return record


def plan_hard(seed: int, out_dir: Path, samples_dir: Path, repeat: int,
              samples: tuple[str, ...], transforms: tuple[str, ...]) -> dict[str, Any]:
    """Call plan for the hard set; reads caches only, never the network."""
    manifest = ensure_hard_set(seed, out_dir, samples_dir, samples, transforms)
    cases = []
    canonical_live = 0
    with cache_dir_scope(hard_dir()):
        for case in manifest["cases"]:
            key = hard_cache_key(out_dir / case["receipt"], out_dir / case["cert"])
            cached = replay_cache.exists(key)
            canonical_live += not cached
            cases.append({**case, "cached": cached})
    n = len(cases)
    return {
        "cases": cases,
        "base_live": canonical_live + n * (repeat - 1),
        "base_replay": n - canonical_live,
        "reread_max": n * repeat,
    }


def plan_normal(samples_dir: Path, repeat: int,
                samples: tuple[str, ...]) -> dict[str, Any]:
    """Call plan for repeat runs over the committed set (run 1 replays)."""
    cases = []
    missing = 0
    with cache_dir_scope(None):
        for sample in samples:
            for variant in NORMAL_VARIANTS:
                images = resolve_sample_images(samples_dir / sample, variant)
                key = hard_cache_key(images[0], images[1])
                cached = replay_cache.exists(key)
                missing += not cached
                cases.append({"sample": sample, "variant": variant, "cached": cached})
    n = len(cases)
    return {
        "cases": cases,
        "base_live": missing + n * (repeat - 1),
        "base_replay": n - missing,
        "reread_max": n * repeat,
    }


def estimate_text(plan: dict[str, Any], label: str) -> str:
    base, re_max = plan["base_live"], plan["reread_max"]
    lo = base * BASE_EST
    hi = base * BASE_EST + re_max * REREAD_EST
    lines = [
        f"{label}: {len(plan['cases'])} cases",
        f"  base reads: {base} live + {plan['base_replay']} replay",
        f"  narrow re-reads: up to {re_max} (only on failed checks)",
        (f"  estimate: ${lo:.2f}-${hi:.2f} "
         f"({base} x ${BASE_EST:.4f} + up to {re_max} x ${REREAD_EST:.4f})"),
    ]
    return "\n".join(lines)


def git_cache_status() -> str:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", "cache/"],
            check=False, capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return "(git unavailable)"
    out = proc.stdout.strip()
    return "(clean)" if not out else out


def _call_cost(calls: list[dict]) -> float:
    """Actual cost; falls back to the plan allowances when rates are missing."""
    total = 0.0
    for call in calls:
        cost = call.get("cost_usd")
        if cost is not None:
            total += cost
        elif call.get("total_tokens", 0) < 2500:
            total += REREAD_EST
        else:
            total += BASE_EST
    return total


def execute(plans: dict[str, Any], repeat: int, max_cost: float,
            provider_factory: Callable[[], Any],
            log_path: Path) -> dict[str, Any]:
    """Run every planned case; aborts past max_cost with partial results.

    Hard run 1 replays from (or records to) cache/hard/; every other live
    call goes to a scratch dir. Callers enrich plan cases with images,
    truth, and unreadable marks before calling.
    """
    results: dict[str, Any] = {"sets": {}, "spent": 0.0, "aborted": False,
                               "cache_before": git_cache_status()}
    with tempfile.TemporaryDirectory(prefix="hard-eval-") as tmp:
        tmpdir = Path(tmp)
        for name, plan in plans.items():
            set_results = []
            for case in plan["cases"]:
                runs = []
                for run in range(1, repeat + 1):
                    canonical = name == "hard" and run == 1
                    replay_dir: Path | None = hard_dir() if name == "hard" else None
                    live_dir = hard_dir() if canonical else tmpdir
                    record = run_once(
                        case["sample"], case["images"], case["truth"],
                        case["unreadable"], replay_dir, live_dir,
                        force_live=run != 1, provider_factory=provider_factory,
                    )
                    record["run"] = run
                    record["canonical"] = canonical
                    runs.append(record)
                    results["spent"] += _call_cost(record["calls"])
                    if results["spent"] > max_cost:
                        results["aborted"] = True
                        break
                set_results.append({**case_summary(case), "truth": case["truth"],
                                    "runs": runs})
                if results["aborted"]:
                    break
            results["sets"][name] = summarize(set_results, repeat)
            results["sets"][name]["gate"] = simulate_gate(set_results)
            results["sets"][name]["cases"] = set_results
            if results["aborted"]:
                break
    results["cache_after"] = git_cache_status()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
    return results


def case_summary(case: dict[str, Any]) -> dict[str, Any]:
    return {k: case[k] for k in ("sample", "transform", "variant", "unreadable")
            if k in case}


def _decision_ready(values: dict[str, Any], truth: dict[str, Any]) -> bool:
    """A stopped run is a correct stop unless the finals were decision-ready."""
    if values.get("total") is None:
        return False
    if truth["kr_cells"] is None:
        return all(a is not None for a in values.get("lines", []))
    cells = values.get("kr_cells") or []
    return len(cells) == 10 and all(c is not None for c in cells)


KR_ONLY_FIELDS = ("kr_cells", "instit")


def _has_kr(truth: dict[str, Any]) -> bool:
    return truth.get("kr_cells") is not None


def _field_ok(metrics: dict[str, Any], field: str) -> bool | None:
    """Run-1 correctness per field; None when the field is not scored."""
    if field in metrics.get("excluded", []):
        return None
    value = metrics.get(field)
    if value == "n/a":
        return None
    if isinstance(value, str) and "/" in value:
        hit, _, total = value.partition("/")
        return hit == total
    return value == "ok"


def summarize(cases: list[dict[str, Any]], repeat: int) -> dict[str, Any]:
    """Field accuracy, agreement, and pipeline metrics over run records."""
    accuracy: dict[str, dict[str, int]] = {f: {"ok": 0, "n": 0} for f in FIELDS}
    mean_ok: dict[str, dict[str, int]] = {f: {"ok": 0, "n": 0} for f in FIELDS}
    agree: dict[str, dict[str, int]] = {f: {"agree": 0, "n": 0} for f in FIELDS}
    caught = {"caught": 0, "base_wrong": 0}
    recovered = {"recovered": 0, "reread": 0}
    stopped = {"stopped": 0, "correct": 0, "n": 0}
    reached = 0
    calls = tokens = 0
    for case in cases:
        runs = case["runs"]
        kr = _has_kr(case.get("truth", {}))
        for field in FIELDS:
            if field in KR_ONLY_FIELDS and not kr:
                continue
            first = _field_ok(runs[0]["final"], field)
            if first is not None:
                accuracy[field]["ok"] += first
                accuracy[field]["n"] += 1
            for run in runs:
                ok = _field_ok(run["final"], field)
                if ok is not None:
                    mean_ok[field]["ok"] += ok
                    mean_ok[field]["n"] += 1
            vals = [json.dumps(run["final_values"][field], sort_keys=True) for run in runs]
            if len(vals) == repeat and repeat > 1:
                agree[field]["agree"] += len(set(vals)) == 1
                agree[field]["n"] += 1
        for run in runs:
            calls += len(run["calls"])
            tokens += sum(c.get("total_tokens", 0) for c in run["calls"])
            reached += run["reached"]
            stopped["n"] += 1
            stopped["stopped"] += run["stopped"]
            ready = _decision_ready(run["final_values"], case.get("truth", {}))
            stopped["correct"] += run["stopped"] and (
                run["wrong_numbers"] > 0 or not ready)
            if run.get("checks_first") is not None:
                base_wrong = run["base_wrongs"] > 0
                caught["base_wrong"] += base_wrong
                caught["caught"] += base_wrong and run["checks_first"] == "FAIL"
            if run.get("verify") is not None:
                recovered["reread"] += 1
                recovered["recovered"] += all(
                    _field_ok(run["final"], f) is not False for f in NUMERIC_FIELDS)
    spent = sum(_call_cost(run["calls"]) for case in cases for run in case["runs"])
    return {"accuracy": accuracy, "mean": mean_ok, "agree": agree, "caught": caught,
            "recovered": recovered, "stopped": stopped, "reached": reached,
            "calls": calls, "tokens": tokens, "spent": spent}


GATE_FIELDS = ("total", "lines", "kr_cells")


def _gate_agree(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Same numbers in both reads: total, line amounts, KR cells."""
    return all(left.get(f) == right.get(f) for f in GATE_FIELDS)


def simulate_gate(cases: list[dict[str, Any]]) -> dict[str, int]:
    """Replay recorded run pairs through the double-read gate (simulated).

    Each pair of recorded runs stands in for two independent verified
    reads: any disagreement in the final total/line amounts/KR cells
    stops the pair for a person, while an agreeing pair inherits the
    first run's recorded pipeline outcome (stopped or leaked wrong
    numbers).
    """
    pairs = stops = leaks = 0
    for case in cases:
        runs = case["runs"]
        for a in range(len(runs)):
            for b in range(a + 1, len(runs)):
                pairs += 1
                if _gate_agree(runs[a]["final_values"], runs[b]["final_values"]):
                    if runs[a]["stopped"]:
                        stops += 1
                    else:
                        leaks += runs[a]["reached"]
                else:
                    stops += 1
    return {"pairs": pairs, "stops": stops, "leaks": leaks}


def format_tables(results: dict[str, Any], repeat: int) -> str:
    out = []
    for name, summary in results["sets"].items():
        out.append(f"## {name} set (repeat {repeat})")
        out.append("")
        out.append(f"| field | run-1 accuracy | mean accuracy | {repeat}-run agreement | n |")
        out.append("|---|---|---|---|---|")
        for field in FIELDS:
            acc = summary["accuracy"][field]
            mean = summary["mean"][field]
            agr = summary["agree"][field]
            a = f"{acc['ok']}/{acc['n']}" if acc["n"] else "-"
            m = f"{mean['ok']}/{mean['n']}" if mean["n"] else "-"
            g = f"{agr['agree']}/{agr['n']}" if agr["n"] else "-"
            out.append(f"| {field} | {a} | {m} | {g} | {acc['n']} |")
        out.append("")
        c, r, s = summary["caught"], summary["recovered"], summary["stopped"]
        gate = summary.get("gate", {})
        out.append("| pipeline | single read | with double-read gate |")
        out.append("|---|---|---|")
        out.append(f"| checks caught a bad reading | {c['caught']}/{c['base_wrong']} | - |")
        out.append(f"| narrow re-read recovered | {r['recovered']}/{r['reread']} | - |")
        out.append(f"| stopped for a person (correct) | {s['stopped']}/{s['n']} ({s['correct']}) "
                   f"| {gate.get('stops', '-')}/{gate.get('pairs', '-')} |")
        out.append("| **wrong numbers that left the pipeline (decision or claim pack)** "
                   f"| **{summary['reached']}** | **{gate.get('leaks', '-')}** |")
        out.append(f"| live calls / tokens / spent | {summary['calls']} / {summary['tokens']} "
                   f"/ ${summary.get('spent', 0.0):.4f} | - |")
        out.append("")
        out.append("The gated column is simulated from the recorded run pairs: each pair "
                   "stands in for two independent verified reads.")
        out.append("")
    if results["aborted"]:
        out.append("ABORTED past --max-cost; results above are partial.")
        out.append("")
    return "\n".join(out)


def reformat(log_path: Path, repeat: int) -> str:
    """Recompute tables from a recorded run log (no network, no model)."""
    results = json.loads(log_path.read_text(encoding="utf-8"))
    for name, entry in results["sets"].items():
        summary = summarize(entry["cases"], repeat)
        summary["gate"] = simulate_gate(entry["cases"])
        summary["cases"] = entry["cases"]
        results["sets"][name] = summary
    return format_tables(results, repeat)


def default_provider_factory() -> Callable[[], Any]:
    def make() -> Any:
        return MetaProvider(live=False)

    return make


def plan_read2(samples_dir: Path, samples: tuple[str, ...]) -> dict[str, Any]:
    """Second-read recordings missing per normal pair; reads caches only."""
    from claimlens.serve import READ2_TAG

    pairs = []
    for sample in samples:
        for variant in NORMAL_VARIANTS:
            images = resolve_sample_images(samples_dir / sample, variant)
            key = hard_cache_key(images[0], images[1]) + READ2_TAG
            cached = (replay_cache.cache_dir() / f"{key}.json").exists()
            pairs.append({"sample": sample, "variant": variant, "key": key,
                          "cached": cached})
    return {"pairs": pairs, "missing": sum(not p["cached"] for p in pairs)}


def record_read2(pairs: list[dict[str, Any]], samples_dir: Path,
                 provider_factory: Callable[[], Any]) -> dict[str, Any]:
    """Record missing second reads under new keys; skips cached pairs."""
    from claimlens.serve import READ2_TAG

    stored: list[str] = []
    spent = 0.0
    for pair in pairs:
        if pair["cached"]:
            continue
        images = resolve_sample_images(samples_dir / pair["sample"], pair["variant"])
        provider = provider_factory()
        provider.read_documents(images, READING_INSTRUCTIONS, reading_schema(),
                                cache_tag=READ2_TAG)
        spent += _call_cost([vars(c) for c in provider.calls])
        stored.append(f"{pair['sample']} {pair['variant']}")
    return {"stored": stored, "spent": spent}


def run_log_path() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("out") / f"hard_eval_{stamp}.json"
