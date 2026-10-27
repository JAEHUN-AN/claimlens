"""Measurement table over all samples and variants (SPEC 6). Replay by default."""

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from claimlens import cache as replay_cache
from claimlens.cache import CacheMissError
from claimlens.checks import all_passed, check_kr_bill, check_kr_lines
from claimlens.prompts import READING_INSTRUCTIONS
from claimlens.providers.meta import MetaProvider
from claimlens.providers.replay import ReplayProvider
from claimlens.reader import reading_schema, resolve_sample_images

SAMPLE_IDS = [
    "A_niseko_wrist",
    "B_chiangmai_dogbite",
    "C_newyork_panic",
    "S2_seoul_worker_bronchitis",
    "S3_us_tourist_hip_fracture",
]

VARIANTS = ["photo", "clean"]


def samples_dir() -> Path:
    return Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples"))


def load_scenarios() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    base = samples_dir()
    for name in ("scenarios.json", "scenarios_inbound.json"):
        path = base / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for sc in data.get("scenarios", []):
            out[sc["id"]] = sc
    return out


def expected_cells_kr(scenario: dict[str, Any]) -> list[int | None]:
    """Ground-truth cells 1-10 from items plus cap/already-paid and formulas."""
    receipt = scenario["documents"][0]["data"]
    items = receipt.get("items", [])
    c1 = sum(i.get("copay", 0) for i in items)
    c2 = sum(i.get("insurer", 0) for i in items)
    c3 = sum(i.get("full", 0) for i in items)
    c4 = sum(i.get("non_covered", 0) for i in items)
    c5 = receipt.get("cap_excess", 0)
    c9 = receipt.get("already_paid", 0)
    c6 = c1 + c2 + c3 + c4
    c7 = c2 + c5
    c8 = (c1 - c5) + c3 + c4
    c10 = c8 - c9
    return [c1, c2, c3, c4, c5, c6, c7, c8, c9, c10]


def ground_truth(scenario: dict[str, Any]) -> dict[str, Any]:
    sid = scenario["id"]
    expected = scenario.get("expected", {})
    receipt_data = scenario["documents"][0]["data"]
    cert_data = scenario["documents"][1]["data"]
    is_kr = sid.startswith(("S2", "S3"))
    if is_kr:
        currency = "KRW"
        if sid.startswith("S2"):
            total = float(expected.get("claimed_krw", 45000))
        else:
            total = float(expected.get("total_krw", 15000000))
        items = receipt_data.get("items", [])
        line_amounts = [
            float(i.get("copay", 0) + i.get("insurer", 0) + i.get("full", 0) + i.get("non_covered", 0))
            for i in items
        ]
        diag_codes = [cert_data.get("code", "")]
        kr_cells: list[int | None] | None = expected_cells_kr(scenario)
        institution: str | None = receipt_data.get("institution_type")
        patient = scenario.get("patient", {})
        if sid.startswith("S2"):
            pii_values = [patient.get("name", ""), patient.get("patient_id", "")]
        else:
            pii_values = [
                patient.get("name", ""),
                patient.get("dob", ""),
                patient.get("passport", ""),
                patient.get("patient_id", ""),
            ]
    else:
        currency = expected.get("currency", "")
        total = float(expected.get("total", 0))
        items = receipt_data.get("items", [])
        line_amounts = [float(i.get("amount", 0)) for i in items]
        diags = cert_data.get("diagnoses", [])
        diag_codes = [d.get("code", "") for d in diags]
        kr_cells = None
        institution = None
        patient = scenario.get("patient", {})
        pii_values = [
            patient.get("name", ""),
            patient.get("dob", ""),
            patient.get("passport", ""),
            patient.get("patient_id", ""),
        ]
    pii_values = [v for v in pii_values if v]
    return {
        "currency": currency,
        "total": total,
        "line_count": len(line_amounts),
        "line_amounts": line_amounts,
        "diag_codes": diag_codes,
        "kr_cells": kr_cells,
        "institution": institution,
        "pii_values": pii_values,
    }


def _amounts_close(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) < 0.01


def compare(sample_id: str, truth: dict[str, Any], reading: dict[str, Any]) -> dict[str, Any]:
    docs = reading.get("documents", [])
    docs_ok = [d.get("doc_type") for d in docs] == ["receipt", "medical_certificate"]
    receipt = docs[0] if docs else {}
    cert = docs[1] if len(docs) > 1 else {}
    currency_ok = receipt.get("currency") == truth["currency"]
    total = receipt.get("total_amount")
    total_ok = total is not None and _amounts_close(total, truth["total"])
    read_lines = receipt.get("line_items", [])
    read_amounts = [float(i.get("amount", 0)) for i in read_lines]
    exp_amounts = truth["line_amounts"]
    lines_count = f"{len(read_amounts)}/{len(exp_amounts)}"
    amounts_ok = len(read_amounts) == len(exp_amounts) and all(
        _amounts_close(a, b) for a, b in zip(read_amounts, exp_amounts)
    )
    read_codes = [d.get("code", "") for d in cert.get("diagnoses", [])]
    exp_codes = truth["diag_codes"]
    diag_hit = sum(1 for a, b in zip(read_codes, exp_codes) if a == b)
    diag_hit = diag_hit if len(read_codes) == len(exp_codes) else 0
    diags = f"{diag_hit}/{len(exp_codes)}"
    bill = receipt.get("kr_bill")
    if truth["kr_cells"] is None:
        kr_cells = "n/a"
        instit = "n/a"
        checks = "n/a"
    else:
        exp_cells = truth["kr_cells"] or []
        if bill is None:
            kr_cells = f"0/{len(exp_cells)}"
            instit = "FAIL"
            checks = "FAIL"
        else:
            hit = sum(1 for n, exp in enumerate(exp_cells, start=1) if bill.get(f"cell_{n}") == exp)
            kr_cells = f"{hit}/{len(exp_cells)}"
            instit = "ok" if bill.get("institution_type") == truth["institution"] else "FAIL"
            full = [*check_kr_bill(bill), *check_kr_lines(receipt)]
            checks = "pass" if all_passed(full) else "FAIL"
    pii_found = set()
    for doc in docs:
        for item in doc.get("pii", []):
            pii_found.add(item.get("value", ""))
    pii_hit = sum(1 for v in truth["pii_values"] if v in pii_found)
    pii = f"{pii_hit}/{len(truth['pii_values'])}"
    return {
        "sample": sample_id,
        "docs": "ok" if docs_ok else "FAIL",
        "currency": "ok" if currency_ok else "FAIL",
        "total": "ok" if total_ok else "FAIL",
        "lines": lines_count,
        "amounts": "ok" if amounts_ok else "FAIL",
        "diags": diags,
        "kr_cells": kr_cells,
        "instit": instit,
        "checks": checks,
        "pii": pii,
    }


def read_with_fallback(sample: Path, variant: str) -> dict[str, Any]:
    """Replay first; record live only when the cache entry is missing."""
    load_dotenv()
    images = resolve_sample_images(sample, variant)
    schema = reading_schema()
    replay = ReplayProvider()
    try:
        result = replay.read_documents(images, READING_INSTRUCTIONS, schema)
        calls = [vars(c) for c in replay.calls]
        return {"result": result, "calls": calls, "provider": "replay"}
    except CacheMissError:
        pass
    live = MetaProvider()
    result = live.read_documents(images, READING_INSTRUCTIONS, schema)
    calls = [vars(c) for c in live.calls]
    return {"result": result, "calls": calls, "provider": "meta"}


def read_open_with_fallback(sample: Path, variant: str) -> dict[str, Any]:
    """Open-weights reading: replay first, record live only when missing."""
    from claimlens.providers.baseten import MODEL as OPEN_MODEL
    from claimlens.providers.baseten import BasetenProvider, reading_tool_schema
    from claimlens.providers.meta import prepare_image

    load_dotenv()
    images = resolve_sample_images(sample, variant)
    schema = reading_schema()
    key_schema = reading_tool_schema(schema)
    blobs = [prepare_image(p) for p in images]
    key = replay_cache.cache_key(blobs, READING_INSTRUCTIONS, key_schema, OPEN_MODEL)
    try:
        payload = replay_cache.load(key)
    except CacheMissError:
        if os.environ.get("CLAIMLENS_PROVIDER", "meta").lower() == "replay":
            raise
        BasetenProvider().read_documents(images, READING_INSTRUCTIONS, schema)
        payload = replay_cache.load(key)
        return {"key_schema": key_schema, "payload": payload, "provider": "baseten"}
    return {"key_schema": key_schema, "payload": payload, "provider": "replay"}


def eval_sample_open(sample_id: str, variant: str, truth: dict[str, Any]) -> dict[str, Any]:
    sample = samples_dir() / sample_id
    try:
        envelope = read_open_with_fallback(sample, variant)
    except (FileNotFoundError, RuntimeError, LookupError) as exc:
        return {"error": str(exc)}
    from claimlens.providers.baseten import MODEL as OPEN_MODEL

    replay = ReplayProvider(model=envelope["payload"].get("model", OPEN_MODEL))
    result = replay.read_documents(
        resolve_sample_images(sample, variant), READING_INSTRUCTIONS, envelope["key_schema"]
    )
    metrics = compare(sample_id, truth, result)
    usage = envelope["payload"].get("usage", {})
    total = int(usage.get("total_tokens", 0))
    reasoning = int(usage.get("reasoning_tokens", 0))
    return {
        "total": metrics["total"],
        "lines": metrics["lines"],
        "checks": metrics["checks"],
        "tokens": f"{total} ({reasoning} reasoning)",
        "latency_ms": envelope["payload"].get("latency_ms"),
        "cost": None,
        "provider": envelope.get("provider", ""),
    }


def eval_sample(sample_id: str, variant: str) -> dict[str, Any]:
    scenarios = load_scenarios()
    scenario = scenarios[sample_id]
    truth = ground_truth(scenario)
    sample = samples_dir() / sample_id
    try:
        envelope = read_with_fallback(sample, variant)
    except (FileNotFoundError, RuntimeError, LookupError) as exc:
        return {"sample": sample_id, "variant": variant, "error": str(exc)}
    metrics = compare(sample_id, truth, envelope["result"])
    metrics["variant"] = variant
    calls = envelope.get("calls", [])
    tokens = sum(c.get("total_tokens", 0) for c in calls)
    cost = sum(c.get("cost_usd", 0) for c in calls if c.get("cost_usd") is not None)
    has_cost = any(c.get("cost_usd") is not None for c in calls)
    metrics["calls"] = len(calls)
    metrics["tokens"] = tokens
    metrics["cost"] = round(cost, 6) if has_cost else None
    metrics["provider"] = envelope.get("provider", "")
    opened = eval_sample_open(sample_id, variant, truth)
    if "error" in opened:
        metrics["open"] = None
    else:
        metrics["open"] = opened
    return metrics


def eval_all() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample_id in SAMPLE_IDS:
        for variant in VARIANTS:
            rows.append(eval_sample(sample_id, variant))
    return rows


def format_markdown(rows: list[dict[str, Any]]) -> str:
    header = (
        "| sample | variant | docs | currency | total | lines | amounts | diags "
        "| kr_cells | instit | checks | pii | calls | tokens | cost "
        "| open_total | open_lines | open_checks | open_tokens | open_latency_ms | open_cost |"
    )
    sep = (
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
        "---|---|---|---|---|---|"
    )
    lines = [header, sep]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['sample']} | {r['variant']} | ERROR: {r['error']} |")
            continue
        cost = "-" if r["cost"] is None else f"${r['cost']:.4f}"
        opened = r.get("open") or {}
        latency = opened.get("latency_ms")
        open_cells = " | ".join(
            [
                str(opened.get("total", "-")),
                str(opened.get("lines", "-")),
                str(opened.get("checks", "-")),
                str(opened.get("tokens", "-")),
                "-" if latency is None else str(latency),
                "-",
            ]
        )
        lines.append(
            f"| {r['sample']} | {r['variant']} | {r['docs']} | {r['currency']} "
            f"| {r['total']} | {r['lines']} | {r['amounts']} | {r['diags']} "
            f"| {r['kr_cells']} | {r['instit']} | {r['checks']} | {r['pii']} "
            f"| {r['calls']} | {r['tokens']} | {cost} | {open_cells} |"
        )
    return "\n".join(lines) + "\n"


def open_translation_row() -> dict[str, Any]:
    """Hosted vs open label translation, both from replay caches."""
    from claimlens.claimpack import translate_labels
    from claimlens.engine import replay_reading
    from claimlens.providers.baseten import MODEL as OPEN_MODEL
    from claimlens.providers.baseten import translate_labels_open
    from claimlens.providers.meta import MODEL as HOSTED_MODEL
    from claimlens.providers.replay import ReplayProvider

    reading = replay_reading("S3_us_tourist_hip_fracture", "photo")
    rows = reading["documents"][0]["kr_bill"]["charge_rows"]
    labels = [r.get("label", "") for r in rows]
    hosted = translate_labels(labels, ReplayProvider())
    opened = translate_labels_open(labels)
    identical = sum(1 for ko in labels if hosted.get(ko) == opened["table"].get(ko))
    usage = opened.get("usage", {})
    total = int(usage.get("total_tokens", 0))
    reasoning = int(usage.get("reasoning_tokens", 0))
    return {
        "step": "S3 row labels",
        "hosted": HOSTED_MODEL,
        "open": OPEN_MODEL,
        "labels": len(labels),
        "identical": f"{identical}/{len(labels)}",
        "open_tokens": f"{total} ({reasoning} reasoning)",
        "open_cost": "-",
    }


def format_open_section(row: dict[str, Any]) -> str:
    header = (
        "| step | hosted model | open model | labels | identical "
        "| open tokens (reasoning) | open cost |"
    )
    sep = "|---|---|---|---|---|---|---|"
    body = (
        f"| {row['step']} | {row['hosted']} | {row['open']} | {row['labels']} "
        f"| {row['identical']} | {row['open_tokens']} | {row['open_cost']} |"
    )
    section = f"{header}\n{sep}\n{body}\n"
    return "## Pack translation: hosted Spark vs Spark Open\n\n" + section


def cache_key_for(sample_id: str, variant: str) -> str:
    from claimlens.providers.meta import MODEL, prepare_image

    images = resolve_sample_images(samples_dir() / sample_id, variant)
    blobs = [prepare_image(p) for p in images]
    return replay_cache.cache_key(blobs, READING_INSTRUCTIONS, reading_schema(), MODEL)
