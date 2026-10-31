"""Local live server: `claimlens serve` (standard library only).

Serves the demo page and a JSON pipeline for real uploads: reading,
checks, re-read, eligibility, consistency, then the engine (when
Neo4j is reachable) or the Claim Pack. Bound to 127.0.0.1, 10 MB
max upload, images only. The API key stays in this process; the
browser only posts images and reads results.
"""

import base64
import binascii
import copy
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BODY_BYTES = 14 * 1024 * 1024
REUSED_LABEL = "recording reused — no model call"
# S2: at most this many live runs decode images at once (memory bound).
MAX_CONCURRENT_RUNS = 4
_RUN_SEMAPHORE = threading.Semaphore(MAX_CONCURRENT_RUNS)

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def live_provider() -> Any:
    """Live Spark provider; reuses caches, never overwrites committed ones."""
    from dotenv import load_dotenv

    from claimlens.providers.meta import MetaProvider

    load_dotenv()
    return MetaProvider(live=True)


def neo4j_up() -> bool:
    try:
        from dotenv import load_dotenv
        from neo4j import GraphDatabase

        load_dotenv()
        driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI"),
            auth=(os.environ.get("NEO4J_USER"), os.environ.get("NEO4J_PASSWORD")),
            connection_timeout=3,
        )
        try:
            driver.verify_connectivity()
        finally:
            driver.close()
    except Exception:  # noqa: BLE001 - connectivity probe: any failure means down
        return False
    return True


def _image_kind(blob: bytes) -> str | None:
    if blob.startswith(JPEG_MAGIC):
        return "jpg"
    if blob.startswith(PNG_MAGIC):
        return "png"
    return None


def match_sample(blobs: list[bytes]) -> str | None:
    """Sample id when every upload byte-matches that sample's photos."""
    from claimlens.engine import samples_dir
    from claimlens.reader import resolve_sample_images

    base = samples_dir()
    if not base.is_dir():
        return None
    wanted = sorted(hashlib.sha256(b).hexdigest() for b in blobs)
    for sample_dir in sorted(base.iterdir()):
        if not sample_dir.is_dir():
            continue
        try:
            images = resolve_sample_images(sample_dir, "photo")
        except FileNotFoundError:
            continue
        known = sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in images)
        if known == wanted:
            return sample_dir.name
    return None


def order_docs(reading: dict[str, Any]) -> dict[str, Any]:
    """Receipt first, certificate second, by the model's own labels."""
    docs = reading.get("documents", [])
    receipt = next((d for d in docs if d.get("doc_type") == "receipt"), None)
    cert = next((d for d in docs if d.get("doc_type") == "medical_certificate"), None)
    if receipt is None or cert is None:
        raise ValueError("Could not tell the receipt from the certificate; upload one of each.")
    return {"documents": [receipt, cert]}


PERSON_FIELDS = ("visa", "korean_employer", "work_related", "entry_date",
                 "alien_registration_date", "korean_national")

FACT_QUESTIONS = {
    "visa": (
        "What visa does the patient hold?",
        "Special visas change when coverage starts (eligibility row 2).",
    ),
    "korean_employer": (
        "Does the patient work for a Korean employer?",
        "Workplace subscribers are covered from the first working day (row 1).",
    ),
    "work_related": (
        "Is this injury or illness work-related?",
        "Work injuries go to industrial-accident insurance first (row 7).",
    ),
    "entry_date": (
        "When did the patient enter Korea (YYYY-MM-DD)?",
        "Coverage starts from entry or registration (rows 2-4).",
    ),
    "alien_registration_date": (
        ("When did the patient register as a foreign resident (YYYY-MM-DD)? "
         "Answer none when never registered."),
        "Workplace and 6-month coverage start from registration (rows 1-4).",
    ),
    "korean_national": (
        "Is the patient a Korean national treated abroad?",
        "Korean nationals treated abroad take the traveller engine path.",
    ),
}

_RUNS: dict[str, dict[str, Any]] = {}
_MAX_RUNS = 20

READ2_TAG = ".read2"


def _fmt_value(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return "unreadable"
    if isinstance(value, float):
        return f"{value:,.0f}" if value.is_integer() else str(value)
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _numbers_differ(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return (left is None) != (right is None)
    try:
        return abs(float(left) - float(right)) >= 0.01
    except (TypeError, ValueError):
        return left != right


def _fmt_stay(value: Any) -> str:
    if value is True:
        return "inpatient"
    if value is False:
        return "outpatient"
    return "unreadable"


def gate_diffs(first: dict[str, Any], second: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Differing fields between two verified readings.

    Returns (label, first value, second value) for the total, each line
    amount, and each KR cell that disagrees, then the C1 identity group:
    currency, country, service date, inpatient stay, diagnosis codes,
    and charge-row cells.
    """
    from claimlens.checks import cell_value, row_value

    first_docs = first.get("documents", [])
    second_docs = second.get("documents", [])
    first = first_docs[0] if first_docs else {}
    second = second_docs[0] if second_docs else {}
    first_cert = first_docs[1] if len(first_docs) > 1 else {}
    second_cert = second_docs[1] if len(second_docs) > 1 else {}
    diffs = []
    if _numbers_differ(first.get("total_amount"), second.get("total_amount")):
        diffs.append(("total", _fmt_value(first.get("total_amount")),
                      _fmt_value(second.get("total_amount"))))
    first_lines = first.get("line_items") or []
    second_lines = second.get("line_items") or []
    if len(first_lines) != len(second_lines):
        diffs.append(("line count", str(len(first_lines)), str(len(second_lines))))
    for pos, (left, right) in enumerate(zip(first_lines, second_lines), start=1):
        if _numbers_differ(left.get("amount"), right.get("amount")):
            diffs.append((f"line {pos} amount", _fmt_value(left.get("amount")),
                          _fmt_value(right.get("amount"))))
    # 56: tax/discount/adjustment lines are printed amounts too.
    first_adj = first.get("adjustment_lines") or []
    second_adj = second.get("adjustment_lines") or []
    if len(first_adj) != len(second_adj):
        diffs.append(("adjustment line count", str(len(first_adj)), str(len(second_adj))))
    for pos, (left, right) in enumerate(zip(first_adj, second_adj), start=1):
        if _numbers_differ(left.get("amount"), right.get("amount")):
            diffs.append((f"adjustment {pos} amount", _fmt_value(left.get("amount")),
                          _fmt_value(right.get("amount"))))
    first_bill = first.get("kr_bill")
    second_bill = second.get("kr_bill")
    if (first_bill is None) != (second_bill is None):
        diffs.append(("KR bill", "read" if first_bill else "unreadable",
                      "read" if second_bill else "unreadable"))
    elif first_bill and second_bill:
        for n in range(1, 11):
            if cell_value(first_bill, n) != cell_value(second_bill, n):
                diffs.append((f"KR cell {n}", _fmt_value(cell_value(first_bill, n)),
                              _fmt_value(cell_value(second_bill, n))))
    for label, left, right in (
        ("currency", first.get("currency"), second.get("currency")),
        ("country", first.get("country"), second.get("country")),
        ("service date", first.get("service_date"), second.get("service_date")),
    ):
        if left != right:
            diffs.append((label, _fmt_value(left), _fmt_value(right)))
    if first.get("inpatient") != second.get("inpatient"):
        diffs.append(("inpatient stay", _fmt_stay(first.get("inpatient")),
                      _fmt_stay(second.get("inpatient"))))
    first_codes = [d.get("code") for d in first_cert.get("diagnoses", [])]
    second_codes = [d.get("code") for d in second_cert.get("diagnoses", [])]
    if len(first_codes) != len(second_codes):
        diffs.append(("diagnosis code count", str(len(first_codes)),
                      str(len(second_codes))))
    for pos, (left, right) in enumerate(zip(first_codes, second_codes), start=1):
        if left != right:
            diffs.append((f"diagnosis code {pos}", _fmt_value(left),
                          _fmt_value(right)))
    if first_bill and second_bill:
        first_rows = first_bill.get("charge_rows") or []
        second_rows = second_bill.get("charge_rows") or []
        if len(first_rows) != len(second_rows):
            diffs.append(("charge row count", str(len(first_rows)),
                          str(len(second_rows))))
        for pos, (left, right) in enumerate(zip(first_rows, second_rows), start=1):
            for n in range(1, 5):
                if row_value(left, n) != row_value(right, n):
                    diffs.append((f"charge row {pos} col {n}",
                                  _fmt_value(row_value(left, n)),
                                  _fmt_value(row_value(right, n))))
    return diffs


def _diff_source(label: str) -> str:
    """Where the value lives in the source reading (H7: shown per option)."""
    photo, inner = _split_photo(label)
    prefix = f"photo {photo} " if photo is not None else ""
    if inner == "total":
        return prefix + "receipt total_amount"
    if inner == "line count":
        return prefix + "receipt line items"
    if inner.startswith("line ") and inner.endswith(" amount"):
        return prefix + f"receipt {inner}"
    if inner == "KR bill":
        return prefix + "receipt KR bill"
    if inner.startswith("KR cell "):
        return prefix + f"receipt {inner}"
    if inner in ("currency", "country", "service date"):
        return prefix + f"receipt {inner.replace(' ', '_')}"
    if inner == "inpatient stay":
        return prefix + "receipt inpatient"
    if inner == "diagnosis code count":
        return prefix + "certificate diagnoses"
    if inner.startswith("diagnosis code "):
        return prefix + f"certificate diagnosis {inner.rsplit(' ', 1)[1]} code"
    if inner == "charge row count":
        return prefix + "receipt charge rows"
    if inner.startswith("charge row "):
        return prefix + f"receipt {inner}"
    return ""


def gate_questions(diffs: list[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """One ask_user question per differing field, both values side by side.

    H7: each resolvable question carries its id plus first/second options
    with the source location, so the screen can offer a real choice.
    Unresolvable rows (documents, failed reads) carry empty options.
    """
    out = []
    for label, left, right in diffs:
        source = _diff_source(label)
        options = (
            [{"id": "first", "label": f"first read: {left}", "source": source},
             {"id": "second", "label": f"second read: {right}", "source": source}]
            if source else []
        )
        out.append({
            "id": label,
            "question": f"{label}: first read {left}, second read {right} — which is printed?",
            "why_needed": "Two independent reads disagreed; a person must pick the printed value.",
            "options": options,
        })
    return out


def gate_choice_ids(diffs: list[tuple[str, str, str]]) -> list[str]:
    """Labels a person can resolve (everything with a source location)."""
    return [label for label, _, _ in diffs if _diff_source(label)]


def _gate_value(docs: list[dict[str, Any]], label: str) -> Any:
    """Read one gate-comparable field out of ordered docs (H7)."""
    import re

    receipt = docs[0] if docs else {}
    cert = docs[1] if len(docs) > 1 else {}
    if label == "total":
        return receipt.get("total_amount")
    if label == "line count":
        return copy.deepcopy(receipt.get("line_items"))
    match = re.fullmatch(r"line (\d+) amount", label)
    if match:
        items = receipt.get("line_items") or []
        return items[int(match.group(1)) - 1].get("amount")
    if label == "KR bill":
        return copy.deepcopy(receipt.get("kr_bill"))
    match = re.fullmatch(r"KR cell (\d+)", label)
    if match:
        return (receipt.get("kr_bill") or {}).get(f"cell_{match.group(1)}")
    if label in ("currency", "country"):
        return receipt.get(label)
    if label == "service date":
        return receipt.get("service_date")
    if label == "inpatient stay":
        return receipt.get("inpatient")
    if label == "diagnosis code count":
        return copy.deepcopy(cert.get("diagnoses"))
    match = re.fullmatch(r"diagnosis code (\d+)", label)
    if match:
        diags = cert.get("diagnoses") or []
        return diags[int(match.group(1)) - 1].get("code")
    if label == "charge row count":
        return copy.deepcopy((receipt.get("kr_bill") or {}).get("charge_rows"))
    match = re.fullmatch(r"charge row (\d+) col (\d+)", label)
    if match:
        rows = (receipt.get("kr_bill") or {}).get("charge_rows") or []
        return rows[int(match.group(1)) - 1].get(f"col_{match.group(2)}")
    raise ValueError(f"Unresolvable choice {label!r}.")


def _gate_assign(docs: list[dict[str, Any]], label: str, value: Any) -> None:
    """Write one person-picked value into ordered docs (H7)."""
    import re

    receipt = docs[0] if docs else {}
    cert = docs[1] if len(docs) > 1 else {}
    if label == "total":
        receipt["total_amount"] = value
    elif label == "line count":
        receipt["line_items"] = value
    elif (match := re.fullmatch(r"line (\d+) amount", label)):
        receipt["line_items"][int(match.group(1)) - 1]["amount"] = value
    elif label == "KR bill":
        receipt["kr_bill"] = value
    elif (match := re.fullmatch(r"KR cell (\d+)", label)):
        receipt["kr_bill"][f"cell_{match.group(1)}"] = value
    elif label in ("currency", "country"):
        receipt[label] = value
    elif label == "service date":
        receipt["service_date"] = value
    elif label == "inpatient stay":
        receipt["inpatient"] = value
    elif label == "diagnosis code count":
        cert["diagnoses"] = value
    elif (match := re.fullmatch(r"diagnosis code (\d+)", label)):
        cert["diagnoses"][int(match.group(1)) - 1]["code"] = value
    elif label == "charge row count":
        receipt["kr_bill"]["charge_rows"] = value
    elif (match := re.fullmatch(r"charge row (\d+) col (\d+)", label)):
        receipt["kr_bill"]["charge_rows"][int(match.group(1)) - 1][
            f"col_{match.group(2)}"] = value
    else:
        raise ValueError(f"Unresolvable choice {label!r}.")


def _list_choice(label: str) -> bool:
    """Whole-list adoptions apply before scalar picks (H7)."""
    return label in ("line count", "KR bill", "diagnosis code count",
                     "charge row count")


def verify_questions(failures: list[tuple[int, list[str]]]) -> list[dict[str, str]]:
    """One ask_user question per read whose receipt checks failed twice."""
    out = []
    for pos, names in failures:
        what = ", ".join(names) if names else "receipt checks"
        out.append({
            "question": f"Read {pos + 1} of 2 failed its receipt checks ({what}); "
                        "a narrow re-read did not fix them — what is printed?",
            "why_needed": "Deterministic checks failed twice; a person must confirm "
                          "the printed numbers before any decision.",
        })
    return out


def missing_facts(person: dict[str, Any] | None) -> list[str]:
    """Panel fields with no answer yet. False is an answer; blank is not.

    C7: never-registered patients answer "none" for the registration
    date; that is an answer (eligibility reads it as unregistered).
    """
    person = person or {}
    missing = []
    for key in PERSON_FIELDS:
        value = person.get(key)
        if (key == "alien_registration_date" and isinstance(value, str)
                and value.strip().lower() == "none"):
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(key)
    return missing


def fact_questions(keys: list[str]) -> list[dict[str, str]]:
    """Missing facts as ask_user questions: same question/why_needed shape."""
    return [
        {"question": FACT_QUESTIONS[key][0], "why_needed": FACT_QUESTIONS[key][1]}
        for key in keys
    ]


def check_person(person: Any) -> dict[str, Any]:
    if person is None:
        return {}
    if not isinstance(person, dict):
        raise TypeError("person must be an object.")
    return person


def check_scenario(scenario: Any, scenarios: dict[str, dict[str, Any]]) -> str | None:
    if scenario is None or scenario == "":
        return None
    if not isinstance(scenario, str) or scenario not in scenarios:
        raise ValueError(f"Unknown scenario: {scenario!r}.")
    return scenario


def _step(steps: list[dict[str, Any]], key: str, label: str, detail: str,
          meta: str, seconds: float, tokens: int = 0) -> None:
    steps.append(
        {"key": key, "label": label, "detail": detail, "meta": meta,
         "seconds": round(seconds, 3), "tokens": tokens}
    )


def _step_usage(provider: Any, since: int) -> tuple[int, bool, bool]:
    """New tokens, whether any call was made, whether all were reused."""
    made = provider.calls[since:]
    fresh = [c for c in made if not getattr(c, "reused", False)]
    return sum(c.total_tokens for c in fresh), bool(made), bool(made) and not fresh


def _live_meta(provider: Any, since: int) -> tuple[str, int]:
    """Honest meta: only a real network call may say 'live'."""
    tokens, _, reused_only = _step_usage(provider, since)
    if reused_only:
        return REUSED_LABEL, 0
    return f"{tokens} tokens (live)", tokens


def _fresh_spend(calls: list[Any]) -> float:
    """Fresh-call spend; reused recordings and unpriced calls cost nothing."""
    total = 0.0
    for call in calls:
        if getattr(call, "reused", False):
            continue
        total += getattr(call, "cost_usd", None) or 0.0
    return total


def _run_spend(providers: list[Any]) -> float:
    """Fresh-call spend across providers; reused recordings cost nothing."""
    return sum(_fresh_spend(getattr(p, "calls", [])) for p in providers)


def _run_retries(providers: list[Any]) -> int:
    """HTTP 429 backoff retries across providers (stubs report 0)."""
    return sum(getattr(p, "retries_429", 0) for p in providers)


def run_live(
    images: list[dict[str, str]],
    person: dict[str, Any] | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    """Full pipeline on uploaded images. Raises ValueError on bad input.

    Two uploads take the guarded 2-image path; 1, 3, 4, 5 or 6 uploads
    take the multi path (per-photo reads merged with provenance).

    When person facts are missing the run pauses after the checks with
    ask_user questions instead of dead-ending; answering continues the
    same run (see run_continue) with no new reading call.
    """
    with _RUN_SEMAPHORE:
        if len(images) == 2:
            return _run_live_guarded(images, person, scenario)
        return _run_live_multi(images, person, scenario)


def _decode_images(images: list[dict[str, str]]) -> list[bytes]:
    """Base64 → bytes plus kind and size checks (shared by both paths)."""
    blobs: list[bytes] = []
    for item in images:
        try:
            blob = base64.b64decode(item.get("data", ""), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(f"{item.get('name', '?')}: not valid base64.") from None
        if _image_kind(blob) is None:
            raise ValueError(f"{item.get('name', '?')}: images only (JPEG or PNG).")
        blobs.append(blob)
    if sum(len(b) for b in blobs) > MAX_UPLOAD_BYTES:
        raise ValueError("Uploads exceed the 10 MB limit.")
    return blobs


def _run_live_guarded(
    images: list[dict[str, str]],
    person: dict[str, Any] | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    from claimlens.checks import receipt_checks
    from claimlens.engine import load_scenarios
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.reader import reading_schema
    from claimlens.verify import DERIVED_LINES_SOURCE, REREAD_READ2_TAG, verify_receipt

    if len(images) != 2:
        raise ValueError("Upload exactly 2 images: the receipt and the certificate.")
    blobs = _decode_images(images)

    person = check_person(person)
    scenarios, _ = load_scenarios()
    declared = check_scenario(scenario, scenarios)

    steps: list[dict[str, Any]] = []
    tokens_total = 0
    providers = [live_provider(), live_provider()]
    with tempfile.TemporaryDirectory(prefix="claimlens-live-") as tmp:
        paths = []
        for item, blob in zip(images, blobs, strict=True):
            suffix = ".jpg" if _image_kind(blob) == "jpg" else ".png"
            path = Path(tmp) / f"upload_{len(paths)}{suffix}"
            path.write_bytes(blob)
            paths.append(path)

        def _read_twice() -> list[dict[str, Any] | None]:
            tags = ["", READ2_TAG]

            def _one(pos: int) -> dict[str, Any] | None:
                try:
                    return providers[pos].read_documents(
                        paths, READING_INSTRUCTIONS, reading_schema(), cache_tag=tags[pos])
                except RuntimeError:
                    return None

            with ThreadPoolExecutor(max_workers=2) as pool:
                return list(pool.map(_one, (0, 1)))

        started = time.monotonic()
        marks = [len(p.calls) for p in providers]
        # Committed sample photos are known upright: skip the rotation
        # probe, so replay needs no new recordings.
        from claimlens.rotation import FAILED_NOTE, upright_pages

        matched = match_sample(blobs)
        if matched is None:
            paths, rot_notes = upright_pages(paths, providers[0], Path(tmp))
        else:
            rot_notes = []
        if FAILED_NOTE in rot_notes:
            # C4: a page we cannot orient is never read; a turned page
            # swaps charge columns identically in both reads.
            tokens = sum(_step_usage(p, mark)[0] for p, mark in zip(providers, marks))
            reused_only = all(_step_usage(p, mark)[2] for p, mark in zip(providers, marks))
            tokens_total += 0 if reused_only else tokens
            _step(steps, "reading", "Reading", f"{FAILED_NOTE}; stopped before reading",
                  REUSED_LABEL if reused_only else f"{tokens} tokens (live)",
                  time.monotonic() - started, 0 if reused_only else tokens)
            return {
                "steps": steps,
                "result": {"badge": "needs_manual_check",
                           "title": "Human review: the rotation check failed.",
                           "note": ""},
                "tokens_total": tokens_total,
                "cost_usd": _run_spend(providers),
                "retries_429": _run_retries(providers),
                "matched_sample": matched,
                "scenario": declared,
                "questions": [{
                    "question": "The rotation check failed; please re-upload "
                                "the pages upright.",
                    "why_needed": "A turned page can swap charge columns "
                                  "identically in both reads, so nothing was read.",
                }],
            }
        raws = _read_twice()
        if all(raw is None for raw in raws):
            raise RuntimeError("Both reads failed; nothing to compare.")
        tokens = sum(_step_usage(p, mark)[0] for p, mark in zip(providers, marks))
        reused_only = all(_step_usage(p, mark)[2] for p, mark in zip(providers, marks))
        meta = REUSED_LABEL if reused_only else f"{tokens} tokens (live)"
        tokens_total += 0 if reused_only else tokens
        detail = "2 documents read twice by Muse Spark"
        if rot_notes:
            detail += "; " + "; ".join(rot_notes)
        _step(steps, "reading", "Reading", detail,
              meta, time.monotonic() - started, 0 if reused_only else tokens)
        readings: list[dict[str, Any]] = []
        order_failed = False
        read_failed: int | None = None
        raw_counts: list[int] = []
        receipt_images: list[int] = []
        for pos, raw in enumerate(raws):
            if raw is None:
                read_failed = pos + 1
                continue
            # Count before order_docs normalizes: a dropped third document
            # must still stop the gate, never pass on the ordered pair.
            raw_counts.append(len(raw.get("documents", [])) if isinstance(raw, dict) else -1)
            docs = raw.get("documents", []) if isinstance(raw, dict) else []
            receipt_idx = next(
                (i for i, d in enumerate(docs) if d.get("doc_type") == "receipt"), 0)
            try:
                readings.append(order_docs(raw))
                receipt_images.append(receipt_idx)
            except ValueError:
                order_failed = True
        receipts = [r["documents"][0] for r in readings]

        started = time.monotonic()
        marks = [len(p.calls) for p in providers]
        details = []
        verify_failed: list[tuple[int, list[str]]] = []
        for pos, receipt in enumerate(receipts):
            checks = receipt_checks(receipt)
            names = f"{sum(c.passed for c in checks)}/{len(checks)} pass"
            tag = "" if pos == 0 else REREAD_READ2_TAG
            verified = verify_receipt(receipt, paths[receipt_images[pos]],
                                      providers[pos], cache_tag=tag)
            receipts[pos] = verified["receipt"]
            readings[pos]["documents"][0] = verified["receipt"]
            detail = f"{names}; re-read: {verified['status']}"
            adjust = verified["receipt"].get("adjustment_lines") or []
            subtotal = verified["receipt"].get("subtotal")
            if adjust or subtotal is not None:
                shown = ", ".join(
                    f"{a.get('kind')} {_fmt_value(a.get('amount'))}"
                    for a in adjust)
                if subtotal is not None:
                    shown += (", " if shown else "") + (
                        f"subtotal {_fmt_value(subtotal)}")
                source = (adjust[0].get("source", "narrow re-read") if adjust
                          else "narrow re-read")
                detail += f"; adjustments: {shown} ({source})"
            derived = [i for i in verified["receipt"].get("line_items") or []
                       if i.get("source") == DERIVED_LINES_SOURCE]
            if derived:
                detail += f"; lines ({DERIVED_LINES_SOURCE})"
            details.append(detail)
            if verified["status"] == "needs_manual_check":
                verify_failed.append((pos, verified.get("failing", [])))
        tokens = sum(_step_usage(p, mark)[0] for p, mark in zip(providers, marks))
        made = any(_step_usage(p, mark)[1] for p, mark in zip(providers, marks))
        reused_only = all(_step_usage(p, mark)[2] for p, mark in zip(providers, marks))
        tokens_total += 0 if reused_only else tokens
        if made:
            meta = ("deterministic + " + REUSED_LABEL) if reused_only else (
                f"deterministic + {tokens} tokens (live)")
        else:
            meta = "deterministic"
        detail = details[0] if details and all(d == details[0] for d in details) else (
            "read 1: " + details[0] + "; read 2: " + details[1] if len(details) == 2
            else "; ".join(details))
        _step(steps, "checks", "Checks", detail, meta, time.monotonic() - started,
              0 if reused_only else tokens)

        if verify_failed:
            return {
                "steps": steps,
                "result": {"badge": "needs_manual_check",
                           "title": "Human review: receipt checks failed.", "note": ""},
                "tokens_total": tokens_total,
                "cost_usd": _run_spend(providers),
                "retries_429": _run_retries(providers),
                "matched_sample": matched,
                "scenario": declared,
                "questions": verify_questions(verify_failed),
            }
        started = time.monotonic()
        read_questions: list[dict[str, str]] | None = None
        if read_failed is not None:
            read_questions = [{
                "question": f"Read {read_failed} of 2 failed; "
                            "the other read alone cannot pass.",
                "why_needed": "Two independent reads are required; "
                              "a person must re-run.",
            }]
            diffs = [("read 2" if read_failed == 2 else "read 1", "2 documents", "failed")]
        elif order_failed or len(receipts) != 2:
            diffs = [("documents", "receipt + certificate", "unreadable")]
        else:
            if len(raw_counts) == 2 and raw_counts[0] != raw_counts[1]:
                diffs = [("documents", f"{raw_counts[0]} documents",
                          f"{raw_counts[1]} documents")]
            else:
                diffs = gate_diffs(readings[0], readings[1])
        if diffs:
            plural = "s" if len(diffs) != 1 else ""
            _step(steps, "double_read", "Double read", f"{len(diffs)} field{plural} differ",
                  "deterministic", time.monotonic() - started)
            if read_questions is None and len(gate_choice_ids(diffs)) == len(diffs):
                # H7: every difference is a pickable field — pause with a
                # run_id so the person answers and continues the same run.
                run = {
                    "reading": readings[0],
                    "steps": steps,
                    "tokens_total": tokens_total,
                    "cost_usd": _run_spend(providers),
                    "retries_429": _run_retries(providers),
                    "matched": matched,
                    "scenario": declared,
                    "person": person,
                    "gate": {"diffs": diffs, "first": readings[0],
                             "second": readings[1]},
                }
                return _pause_run(
                    run, None, badge="needs_manual_check",
                    title=("Human review: two reads disagreed — "
                           "pick the printed value for each field."),
                    questions=gate_questions(diffs),
                )
            return {
                "steps": steps,
                "result": {"badge": "needs_manual_check",
                           "title": "Human review: two reads disagreed.", "note": ""},
                "tokens_total": tokens_total,
                "cost_usd": _run_spend(providers),
                "retries_429": _run_retries(providers),
                "matched_sample": matched,
                "scenario": declared,
                "questions": read_questions or gate_questions(diffs),
            }
        _step(steps, "double_read", "Double read", "agree",
              "deterministic", time.monotonic() - started)

        reading = readings[0]
        provider = providers[0]
        run = {
            "reading": reading,
            "steps": steps,
            "tokens_total": tokens_total,
            "cost_usd": _run_spend(providers),
            "retries_429": _run_retries(providers),
            "matched": matched,
            "scenario": declared,
            "person": person,
        }
        if missing_facts(person):
            return _pause_run(run)
        return _finish_run(provider, run)


def _payable(doc: dict[str, Any]) -> bool:
    """A receipt, or an 'other' page that carries a total (card slip)."""
    if doc.get("doc_type") == "receipt":
        return True
    return doc.get("doc_type") == "other" and doc.get("total_amount") is not None


def _merge_payables(payables: list[tuple[int, dict[str, Any]]],
                    cert: dict[str, Any] | None, names: list[str],
                    cert_photo: int | None = None
                    ) -> tuple[dict[str, Any], dict[str, Any]]:
    """50: verify-shaped receipts in, one merged reading plus provenance.

    Raises ValueError with the human-facing reason when the set cannot
    merge (mixed currency/country, Korean multi, unmatched slip).
    """
    from claimlens.checks import receipt_checks

    receipts = [(photo, doc) for photo, doc in payables]
    currencies = {doc.get("currency") for _, doc in receipts}
    if len(currencies) > 1:
        raise ValueError("mixed currencies: upload receipts in one currency at a time.")
    countries = {doc.get("country") for _, doc in receipts}
    if len(countries) > 1:
        raise ValueError("mixed countries: upload one country at a time.")
    if len(receipts) > 1 and any(doc.get("kr_bill") for _, doc in receipts):
        raise ValueError("several Korean bills are separate visits; "
                         "upload each visit separately.")
    kept: list[tuple[int, dict[str, Any]]] = []
    photos: list[dict[str, Any]] = []
    for photo, doc in receipts:
        total = doc.get("total_amount")
        match = next(((p, d) for p, d in kept
                      if d.get("total_amount") is not None and total is not None
                      and abs(d["total_amount"] - total) < 0.01), None)
        lines = doc.get("line_items") or []
        if match is not None and (not lines or not (match[1].get("line_items") or [])):
            photos.append({"photo": photo, "file": names[photo - 1],
                           "total": total, "currency": doc.get("currency"),
                           "status": "deduped",
                           "note": (f"photo {match[0]} shows the same amount; "
                                    "counted once")})
            continue
        if match is not None:
            raise ValueError(
                f"photo {photo} ({total}) matches photo {match[0]} but both "
                "look like bills; upload them separately.")
        if not lines:
            raise ValueError(
                f"photo {photo} looks like a payment slip but matches no "
                "bill total; upload the matching bill with it.")
        kept.append((photo, doc))
        note = ""
        doc_adjust = doc.get("adjustment_lines") or []
        doc_subtotal = doc.get("subtotal")
        if doc_adjust or doc_subtotal is not None:
            shown = ", ".join(
                f"{a.get('kind')} {_fmt_value(a.get('amount'))}"
                for a in doc_adjust)
            if doc_subtotal is not None:
                shown += (", " if shown else "") + (
                    f"subtotal {_fmt_value(doc_subtotal)}")
            source = (doc_adjust[0].get("source", "narrow re-read")
                      if doc_adjust else "narrow re-read")
            note = f"adjustments: {shown} ({source})"
        photos.append({"photo": photo, "file": names[photo - 1],
                       "total": total, "currency": doc.get("currency"),
                       "status": "kept", "note": note})
    merged_total = round(sum(doc["total_amount"] for _, doc in kept), 2)
    first = kept[0][1]
    merged = {
        "doc_type": "receipt",
        "country": first.get("country"),
        "currency": first.get("currency"),
        "total_amount": merged_total,
        "service_date": first.get("service_date"),
        "inpatient": any(bool(doc.get("inpatient")) for _, doc in kept),
        "line_items": [item for _, doc in kept
                       for item in (doc.get("line_items") or [])],
        "pii": first.get("pii", []),
        "provider_name": first.get("provider_name", ""),
        "institution": first.get("institution", {}),
        "kr_bill": None,
    }
    all_adjust = [{**adj, "photo": photo}
                  for photo, doc in kept
                  for adj in (doc.get("adjustment_lines") or [])]
    if all_adjust:
        merged["adjustment_lines"] = all_adjust
    failing = [c.name for c in receipt_checks(merged) if not c.passed]
    if failing:
        raise ValueError(f"merged receipt fails checks ({', '.join(failing)}).")
    if cert is not None and cert_photo is not None:
        photos.append({"photo": cert_photo, "file": names[cert_photo - 1],
                       "total": None, "currency": None,
                       "status": "certificate", "note": ""})
    merge = {"photos": sorted(photos, key=lambda p: p["photo"]),
             "merged_total": merged_total, "currency": first.get("currency")}
    return {"documents": [merged, cert or {}]}, merge


def _adopt_multi_resolved(run: dict[str, Any]) -> None:
    """Re-merge after gate picks (H7+50); ValueError re-pauses on conflict."""
    multi = run["multi"]
    resolved = run["gate_resolved"]
    payables: list[tuple[int, dict[str, Any]]] = []
    for photo in multi["payable_photos"]:
        if photo in resolved:
            payables.append((photo, resolved[photo][0]))
        else:
            payables.append((photo, multi["verified"][photo][0]))
    cert = None
    if multi["cert_photo"] is not None:
        photo = multi["cert_photo"]
        if photo in resolved:
            cert = resolved[photo][1]
        else:
            cert = multi["verified"][photo][0]
    reading, merge = _merge_payables(payables, cert, multi["names"],
                                     multi["cert_photo"])
    run["reading"] = reading
    run["merge"] = merge


def _run_live_multi(
    images: list[dict[str, str]],
    person: dict[str, Any] | None = None,
    scenario: str | None = None,
) -> dict[str, Any]:
    """50: 1–5 receipts plus 0–1 certificate, read per photo then merged.

    The 2-image path keeps its own function and recordings untouched;
    this path only runs for 1, 3, 4, 5 or 6 uploads.
    """
    from claimlens.engine import load_scenarios
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.reader import reading_schema
    from claimlens.rotation import FAILED_NOTE, upright_pages
    from claimlens.verify import DERIVED_LINES_SOURCE, REREAD_READ2_TAG, verify_receipt

    if len(images) not in (1, 3, 4, 5, 6):
        raise ValueError("Upload 1 to 6 images: up to 5 receipts and 1 certificate.")
    blobs = _decode_images(images)
    names = [item.get("name", f"photo{i}") for i, item in enumerate(images, start=1)]

    person = check_person(person)
    scenarios, _ = load_scenarios()
    declared = check_scenario(scenario, scenarios)

    steps: list[dict[str, Any]] = []
    tokens_total = 0
    providers = [live_provider(), live_provider()]
    with tempfile.TemporaryDirectory(prefix="claimlens-multi-") as tmp:
        started = time.monotonic()
        paths = []
        for pos, blob in enumerate(blobs):
            suffix = ".jpg" if _image_kind(blob) == "jpg" else ".png"
            path = Path(tmp) / f"upload_{pos}{suffix}"
            path.write_bytes(blob)
            paths.append(path)
        paths, rot_notes = upright_pages(paths, providers[0], Path(tmp))
        if FAILED_NOTE in rot_notes:
            # C4, same as the 2-image path: a page we cannot orient stops
            # before any read.
            tokens = sum(_step_usage(p, mark)[0]
                         for p, mark in zip(providers, (0, 0)))
            reused_only = all(_step_usage(p, mark)[2]
                              for p, mark in zip(providers, (0, 0)))
            tokens_total += 0 if reused_only else tokens
            _step(steps, "reading", "Reading",
                  f"{FAILED_NOTE}; stopped before reading",
                  REUSED_LABEL if reused_only else f"{tokens} tokens (live)",
                  time.monotonic() - started, 0 if reused_only else tokens)
            return {
                "steps": steps,
                "result": {"badge": "needs_manual_check",
                           "title": "Human review: the rotation check failed.",
                           "note": ""},
                "tokens_total": tokens_total,
                "cost_usd": _run_spend(providers),
                "retries_429": _run_retries(providers),
                "matched_sample": None,
                "scenario": declared,
                "questions": [{
                    "question": "The rotation check failed; please re-upload "
                                "the pages upright.",
                    "why_needed": "A turned page can swap charge columns "
                                  "identically in both reads, so nothing was read.",
                }],
            }

        started = time.monotonic()
        marks = [len(p.calls) for p in providers]
        reads: list[list[dict[str, Any] | None]] = [[], []]
        for pos, provider in enumerate(providers):
            for path in paths:
                try:
                    reads[pos].append(provider.read_documents(
                        [path], READING_INSTRUCTIONS, reading_schema(),
                        cache_tag="" if pos == 0 else READ2_TAG))
                except RuntimeError:
                    reads[pos].append(None)
        failed_photos = [i + 1 for i in range(len(paths))
                         if reads[0][i] is None or reads[1][i] is None]
        if failed_photos:
            names_failed = ", ".join(f"photo {i}" for i in failed_photos)
            return _terminal_multi(
                steps, providers, tokens_total, started, declared,
                f"Photos read with {len(failed_photos)} unreadable ({names_failed}).",
                "reads_failed",
                [{"question": (f"{names_failed} could not be read; re-upload "
                               "sharper photos of the same pages."),
                  "why_needed": "Nothing was decided from an unread photo."}])
        tokens = sum(_step_usage(p, mark)[0] for p, mark in zip(providers, marks))
        reused_only = all(_step_usage(p, mark)[2] for p, mark in zip(providers, marks))
        meta = REUSED_LABEL if reused_only else f"{tokens} tokens (live)"
        tokens_total += 0 if reused_only else tokens
        detail = f"{len(paths)} photos read twice by Muse Spark"
        if rot_notes:
            detail += "; " + "; ".join(rot_notes)
        _step(steps, "reading", "Reading", detail,
              meta, time.monotonic() - started, 0 if reused_only else tokens)

        started = time.monotonic()
        payables: dict[int, list[dict[str, Any]]] = {}
        certs: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
        for idx in range(len(paths)):
            docs1 = reads[0][idx].get("documents", []) if reads[0][idx] else []
            docs2 = reads[1][idx].get("documents", []) if reads[1][idx] else []
            if not docs1 or not docs2:
                return _terminal_multi(
                    steps, providers, tokens_total, started, declared,
                    f"Photo {idx + 1} read no documents.",
                    "photo_unreadable",
                    [{"question": (f"Photo {idx + 1} could not be read; re-upload "
                                   "a sharper photo of the same page."),
                      "why_needed": "Nothing was decided from an unread photo."}])
            pay1 = [d for d in docs1 if _payable(d)]
            pay2 = [d for d in docs2 if _payable(d)]
            cert1 = [d for d in docs1 if d.get("doc_type") == "medical_certificate"]
            cert2 = [d for d in docs2 if d.get("doc_type") == "medical_certificate"]
            if len(pay1) != len(pay2) or len(cert1) != len(cert2):
                return _terminal_multi(
                    steps, providers, tokens_total, started, declared,
                    f"Photo {idx + 1} split into documents differently.",
                    "photo_split",
                    [{"question": (f"Photo {idx + 1} read as different documents "
                                   "in the two reads; re-upload it on its own."),
                      "why_needed": "The two reads must agree on what each photo shows."}])
            if pay1:
                payables[idx + 1] = [pay1, pay2]
            if cert1:
                certs[idx + 1] = (cert1[0], cert2[0])
        photo_ids = sorted(payables)
        if not photo_ids:
            return _terminal_multi(
                steps, providers, tokens_total, started, declared,
                "No receipt found in the uploads.",
                "no_receipt",
                [{"question": "No receipt was found; upload at least one receipt photo.",
                  "why_needed": "A claim needs at least one bill to price."}])
        if len(photo_ids) > 5:
            return _terminal_multi(
                steps, providers, tokens_total, started, declared,
                f"{len(photo_ids)} receipts found.",
                "too_many_receipts",
                [{"question": ("More than 5 receipts were found; split them "
                               "into separate claims."),
                  "why_needed": "One run merges at most 5 receipts."}])
        if len(certs) > 1:
            return _terminal_multi(
                steps, providers, tokens_total, started, declared,
                f"{len(certs)} certificates found.",
                "too_many_certs",
                [{"question": ("More than 1 certificate was found; upload "
                               "at most one certificate per claim."),
                  "why_needed": "One run follows a single certificate."}])
        cert_photo = next(iter(certs)) if certs else None
        if cert_photo is None:
            return _terminal_multi(
                steps, providers, tokens_total, started, declared,
                f"{len(photo_ids)} receipt(s) read; no certificate.",
                "certificate_missing",
                [{"question": ("No doctor's certificate was found. Re-upload "
                               "the receipts together with the certificate for "
                               "this visit."),
                  "why_needed": ("A claim is never decided without the "
                                 "doctor's certificate.")}])
        # Unmergeable sets stop before verify burns re-reads. A field
        # only stops the run when NO single value can win every photo's
        # gate: each photo offers its two reads' values, and the run
        # continues when one value is possible everywhere.
        sides = {photo: (pair[0][0], pair[1][0])
                 for photo, pair in payables.items()}
        for field, noun in (("currency", "currencies"), ("country", "countries")):
            options = [{a.get(field), b.get(field)} for a, b in sides.values()]
            if not set.intersection(*options):
                return _terminal_multi(
                    steps, providers, tokens_total, started, declared,
                    f"Mixed {noun} across photos.",
                    f"mixed_{field}",
                    [{"question": (f"mixed {noun}: upload receipts in one "
                                    f"{field} at a time. Re-upload accordingly."),
                      "why_needed": ("Receipts in different currencies or "
                                     "countries never merge into one payout.")}])
        kr_locked = sum(1 for a, b in sides.values()
                        if a.get("kr_bill") and b.get("kr_bill"))
        if kr_locked > 1:
            return _terminal_multi(
                steps, providers, tokens_total, started, declared,
                "Several Korean bills found.",
                "korean_multi",
                [{"question": ("Several Korean bills were found; upload each "
                               "visit separately."),
                  "why_needed": ("Korean bills belong to separate visits and "
                                 "are never merged into one payout.")}])

        started = time.monotonic()
        verified: dict[int, list[dict[str, Any]]] = {}
        checked = 0
        slips = 0
        for photo in photo_ids:
            photo_sides = []
            lineless = False
            for pos in (0, 1):
                raw = payables[photo][pos][0]
                if not (raw.get("line_items") or []):
                    # A payment slip has no lines to check; the merge only
                    # keeps it when its total matches a verified bill total,
                    # and the gate still requires both reads to agree on it.
                    lineless = True
                    photo_sides.append(raw)
                    continue
                tag = "" if pos == 0 else REREAD_READ2_TAG
                outcome = verify_receipt(raw, paths[photo - 1],
                                         providers[pos], cache_tag=tag)
                checked += 1
                if outcome["status"] != "verified":
                    failing = ", ".join(outcome.get("failing", []))
                    return _terminal_multi(
                        steps, providers, tokens_total, started, declared,
                        f"Photo {photo} failed its receipt checks.",
                        "verify_failed",
                        [{"question": (f"Read {pos + 1} of 2 failed its receipt "
                                       f"checks (photo {photo}: {failing}); re-upload "
                                       "a sharper photo of that receipt."),
                          "why_needed": ("A receipt whose numbers do not add up "
                                         "never reaches a decision.")}])
                photo_sides.append(outcome["receipt"])
            verified[photo] = photo_sides
            slips += lineless
        detail = f"{checked}/{checked} pass"
        if slips:
            plural = "s" if slips != 1 else ""
            detail += (f"; {slips} payment slip{plural} "
                       "matched to a bill at merge")
        adjust_notes = []
        adjust_source = "narrow re-read"
        for photo in photo_ids:
            for a in verified[photo][0].get("adjustment_lines") or []:
                adjust_source = a.get("source", adjust_source)
                adjust_notes.append(
                    f"photo {photo}: {a.get('kind')} "
                    f"{_fmt_value(a.get('amount'))}")
            subtotal = verified[photo][0].get("subtotal")
            if subtotal is not None:
                adjust_notes.append(
                    f"photo {photo} subtotal {_fmt_value(subtotal)}")
        if adjust_notes:
            detail += (f"; adjustments ({adjust_source}): "
                       + "; ".join(adjust_notes))
        derived_notes = []
        for photo in photo_ids:
            lines = verified[photo][0].get("line_items") or []
            if any(i.get("source") == DERIVED_LINES_SOURCE
                   for i in lines):
                derived_notes.append(
                    f"photo {photo} lines ({DERIVED_LINES_SOURCE})")
        if derived_notes:
            detail += "; " + "; ".join(derived_notes)
        _step(steps, "checks", "Checks", detail,
              "deterministic", time.monotonic() - started)

        started = time.monotonic()
        pairs = []
        prefixed: list[tuple[int, str, str, str]] = []
        for photo in photo_ids:
            first = {"documents": [verified[photo][0]]}
            second = {"documents": [verified[photo][1]]}
            pairs.append({"first": first, "second": second, "photo": photo,
                          "cert": False})
            for label, left, right in gate_diffs(first, second):
                prefixed.append((photo, label, left, right))
        cert_pair = {"first": {"documents": [{}, certs[cert_photo][0]]},
                     "second": {"documents": [{}, certs[cert_photo][1]]},
                     "photo": cert_photo, "cert": True}
        pairs.append(cert_pair)
        for label, left, right in gate_diffs(cert_pair["first"], cert_pair["second"]):
            prefixed.append((cert_photo, label, left, right))
        if prefixed:
            plural = "s" if len(prefixed) != 1 else ""
            _step(steps, "double_read", "Double read",
                  f"{len(prefixed)} field{plural} differ",
                  "deterministic", time.monotonic() - started)
            diffs = [(f"photo {photo} {label}", left, right)
                     for photo, label, left, right in prefixed]
            run = {
                "reading": None,
                "steps": steps,
                "tokens_total": tokens_total,
                "cost_usd": _run_spend(providers),
                "retries_429": _run_retries(providers),
                "matched": None,
                "scenario": declared,
                "person": person,
                "multi": {"payable_photos": photo_ids, "cert_photo": cert_photo,
                          "verified": {p: [dict(v[0]), dict(v[1])]
                                       for p, v in verified.items()},
                          "names": names},
                "gate": {"diffs": diffs, "pairs": pairs},
            }
            run["multi"]["verified"][cert_photo] = [
                dict(certs[cert_photo][0]), dict(certs[cert_photo][1])]
            return _pause_run(
                run, None, badge="needs_manual_check",
                title=("Human review: two reads disagreed — "
                       "pick the printed value for each field."),
                questions=gate_questions(diffs),
            )
        _step(steps, "double_read", "Double read", "agree",
              "deterministic", time.monotonic() - started)

        started = time.monotonic()
        try:
            reading, merge = _merge_payables(
                [(photo, verified[photo][0]) for photo in photo_ids],
                certs[cert_photo][0], names, cert_photo)
        except ValueError as exc:
            return _terminal_multi(
                steps, providers, tokens_total, started, declared,
                f"{len(photo_ids)} receipt(s) read; not merged.",
                "merge_refused",
                [{"question": f"{exc} Re-upload accordingly.",
                  "why_needed": "Receipts that cannot merge never reach a decision."}])
        kept = [p for p in merge["photos"] if p["status"] == "kept"]
        dropped = [p for p in merge["photos"] if p["status"] == "deduped"]
        detail = "; ".join(f"photo {p['photo']}: {_fmt_value(p['total'])}"
                           for p in kept)
        detail += f"; merged {_fmt_value(merge['merged_total'])} {merge['currency']}"
        for p in dropped:
            detail += f"; photo {p['photo']} deduped ({p['note']})"
        _step(steps, "merge", "Merge", detail, "deterministic",
              time.monotonic() - started)

        provider = providers[0]
        run = {
            "reading": reading,
            "steps": steps,
            "tokens_total": tokens_total,
            "cost_usd": _run_spend(providers),
            "retries_429": _run_retries(providers),
            "matched": None,
            "scenario": declared,
            "person": person,
            "multi": {"payable_photos": photo_ids, "cert_photo": cert_photo,
                      "verified": {p: [dict(v[0]), dict(v[1])]
                                   for p, v in verified.items()},
                      "names": names},
            "merge": merge,
        }
        if missing_facts(person):
            return _pause_run(run)
        return _finish_run(provider, run)


_MULTI_LABELS = {
    "reads_failed": "Reading", "photo_unreadable": "Reading",
    "photo_split": "Reading", "no_receipt": "Upload",
    "too_many_receipts": "Upload", "too_many_certs": "Upload",
    "certificate_missing": "Upload", "mixed_currency": "Upload",
    "mixed_country": "Upload", "korean_multi": "Upload",
    "verify_failed": "Checks", "merge_refused": "Merge",
}


def _terminal_multi(steps: list[dict[str, Any]], providers: list[Any],
                    tokens_total: int, started: float, declared: str | None,
                    detail: str, key: str,
                    questions: list[dict[str, str]]) -> dict[str, Any]:
    """A multi stop: one terminal step plus the human-facing questions."""
    _step(steps, key, _MULTI_LABELS[key], detail,
          "stopped before decision", time.monotonic() - started)
    return {
        "steps": steps,
        "result": {"badge": "needs_manual_check",
                   "title": f"Human review: {detail[0].lower() + detail[1:]}.",
                   "note": ""},
        "tokens_total": tokens_total,
        "cost_usd": _run_spend(providers),
        "retries_429": _run_retries(providers),
        "matched_sample": None,
        "scenario": declared,
        "questions": questions,
    }


def _pause_run(run: dict[str, Any], run_id: str | None = None, *,
               badge: str = "need_facts", title: str | None = None,
               questions: list[dict[str, Any]] | None = None,
               ) -> dict[str, Any]:
    """Park a run; the answer continues it under the same run_id.

    The default pause asks the missing person facts; gate, blocker,
    product and engine pauses pass their own badge/title/questions.
    """
    if questions is None:
        missing = missing_facts(run["person"])
        plural = "s" if len(missing) != 1 else ""
        title = title or f"Answer {len(missing)} question{plural} to continue."
        questions = fact_questions(missing)
    if run_id is None:
        run_id = secrets.token_urlsafe(16)
    _RUNS[run_id] = run
    while len(_RUNS) > _MAX_RUNS:
        _RUNS.pop(next(iter(_RUNS)))
    response: dict[str, Any] = {
        "steps": run["steps"],
        "result": {"badge": badge, "title": title or "", "note": ""},
        "tokens_total": run["tokens_total"],
        "cost_usd": run.get("cost_usd", 0.0),
        "retries_429": run.get("retries_429", 0),
        "matched_sample": run["matched"],
        "scenario": run["scenario"],
        "questions": questions,
        "run_id": run_id,
    }
    if run.get("resolved"):
        response["answers"] = run["resolved"]
    if run.get("merge"):
        response["merge"] = run["merge"]
    return response


def _check_resolutions(resolutions: Any) -> dict[str, Any]:
    if resolutions is None:
        return {}
    if not isinstance(resolutions, dict):
        raise ValueError("resolutions must be an object.")  # noqa: TRY004 - route maps ValueError to 400
    return resolutions


def _resolve_gate(run: dict[str, Any], resolutions: dict[str, Any]) -> None:
    """Apply the person's picks onto a verified read (H7, in place).

    Raises ValueError naming what is missing or malformed; the caller
    re-pauses when the picked values fail the receipt checks.
    """
    from claimlens.checks import receipt_checks

    gate = run.get("gate") or {}
    diffs = gate.get("diffs", [])
    ids = [label for label, _, _ in diffs]
    unknown = [key for key in resolutions if key not in ids]
    if unknown:
        raise ValueError(f"Unknown choices: {', '.join(sorted(unknown))}.")
    missing = [label for label in ids if label not in resolutions]
    if missing:
        raise ValueError(f"Unresolved choices: {', '.join(missing)}.")
    pairs = gate.get("pairs")
    if pairs is None:
        pairs = [{"first": gate["first"], "second": gate["second"], "photo": None,
                  "cert": False}]
    by_photo = {p["photo"]: p for p in pairs}
    resolved_docs: dict[int | None, list[dict[str, Any]]] = {}
    picks: list[str] = []
    ordered = sorted(ids, key=lambda label: (not _list_choice(_inner(label)), label))
    for label in ordered:
        pick = resolutions[label]
        if pick not in ("first", "second"):
            raise ValueError(f"Choice {label!r} must be 'first' or 'second'.")
        photo, inner = _split_photo(label)
        pair = by_photo[photo]
        if photo not in resolved_docs:
            resolved_docs[photo] = copy.deepcopy(pair["first"].get("documents", []))
        docs = resolved_docs[photo]
        side = pair["first" if pick == "first" else "second"].get("documents", [])
        _gate_assign(docs, inner, _gate_value(side, inner))
        picks.append(f"{label} ← {pick} read {_fmt_value(_gate_value(side, inner))}")
    run["resolved"] = {**run.get("resolved", {}),
                       "gate": {label: resolutions[label] for label in ids}}
    run["gate_resolved"] = resolved_docs
    run["_resolve_picks"] = picks
    failing: list[str] = []
    for photo, docs in resolved_docs.items():
        if by_photo[photo].get("cert"):
            continue  # certificates carry no receipt checks
        failing += [c.name for c in receipt_checks(docs[0] if docs else {})
                    if not c.passed]
    run["_resolve_failing"] = sorted(set(failing))


def _split_photo(label: str) -> tuple[int | None, str]:
    import re

    match = re.fullmatch(r"photo (\d+) (.*)", label)
    if match:
        return int(match.group(1)), match.group(2)
    return None, label


def _inner(label: str) -> str:
    return _split_photo(label)[1]


def resolve_eligibility(person: dict[str, Any],
                      receipt: dict[str, Any]) -> dict[str, str]:
    """H1: serve-level eligibility — the traveller path or the NHI rows.

    A Korean national treated outside Korea takes the traveller engine
    path; everyone else is decided by the eligibility rows. Declared
    scenarios never grant eligibility or a policy (H2).
    """
    from claimlens.eligibility import check_eligibility, service_date_of

    abroad = (receipt.get("country") or "") not in ("", "KR")
    if person.get("korean_national") is True and abroad:
        return {"outcome": "traveller_abroad", "rule": "engine_path",
                "basis": "Korean traveller abroad — engine path."}
    return check_eligibility(person, service_date_of(receipt))


def _dental_flag(receipt: dict[str, Any], cert: dict[str, Any]) -> str:
    """T6: dental treatment is flagged for a reviewer, never auto-decided."""
    import re

    for diag in cert.get("diagnoses", []) or []:
        code = re.sub(r"[^A-Za-z0-9]", "", diag.get("code") or "").upper()
        if re.fullmatch(r"K(0\d|1[0-4])\d*", code):
            return f"diagnosis {diag.get('code')}"
    for item in receipt.get("line_items", []) or []:
        text = f"{item.get('description', '')} {item.get('category', '')}".lower()
        if "dental" in text:
            return f"billed line {item.get('description') or 'dental'}"
    return ""


def _bank_finish_spend(run: dict[str, Any], provider: Any, mark_calls: int,
                       mark_retries: int) -> None:
    """Fold this finish's fresh cost/retries into the run before a pause.

    Tokens are already in run["tokens_total"] via the local counter; only
    cost and retries need banking here.
    """
    run["cost_usd"] = run.get("cost_usd", 0.0) + _fresh_spend(
        provider.calls[mark_calls:])
    run["retries_429"] = run.get("retries_429", 0) + (
        getattr(provider, "retries_429", 0) - mark_retries)


def _finish_run(provider: Any, run: dict[str, Any],
                run_id: str | None = None) -> dict[str, Any]:
    """Eligibility, consistency, and decision on a run with full facts."""
    from claimlens.consistency import deterministic_findings, spark_findings
    from claimlens.engine import (
        build_inputs,
        copay_rate_from_bill,
        live_adjudicate,
    )

    reading = run["reading"]
    # A continued run re-finishes: these steps are recomputed, not doubled.
    run["steps"] = [s for s in run["steps"]
                    if s["key"] not in ("eligibility", "consistency", "decision")]
    steps = run["steps"]
    tokens_total = run["tokens_total"]
    matched = run["matched"]
    declared = run["scenario"]
    person = run["person"]
    receipt, cert = reading["documents"]
    mark_calls = len(provider.calls)
    mark_retries = getattr(provider, "retries_429", 0)
    started = time.monotonic()
    eligibility = resolve_eligibility(person, receipt)
    _step(steps, "eligibility", "Eligibility",
          f"{eligibility['outcome']} ({eligibility['rule']})",
          "deterministic", time.monotonic() - started)

    started = time.monotonic()
    mark = len(provider.calls)
    ruled = deterministic_findings(receipt, cert)
    overridden = set(run.get("resolved_blockers", {}))
    ruled = [f for f in ruled
             if not (f["severity"] == "blocker" and f["kind"] in overridden)]
    if run.get("sparked") is not None and not run.get("readings_changed"):
        sparked, dropped = run["sparked"], 0
    else:
        sparked, dropped = spark_findings(receipt, cert, provider)
        run["sparked"] = sparked
    run.pop("readings_changed", None)
    meta, tokens = _live_meta(provider, mark)
    tokens_total += tokens
    blockers = [f for f in ruled + sparked if f["severity"] == "blocker"]
    confirmed = f"; person confirmed {len(overridden)}" if overridden else ""
    _step(steps, "consistency", "Consistency",
          f"{len(blockers)} blockers, {len(ruled + sparked) - len(blockers)} notes"
          + (f"; {dropped} dropped quotes" if dropped else "") + confirmed,
          meta, time.monotonic() - started, tokens)

    started = time.monotonic()
    note = ""
    stop_questions: list[dict[str, str]] = []
    if blockers:
        rule_blockers = [f for f in blockers if f.get("layer") == "rule"]
        if len(rule_blockers) == len(blockers):
            # H8: every blocker is answerable — pause for picks/notes.
            run["blockers"] = rule_blockers
            run["tokens_total"] = tokens_total
            _bank_finish_spend(run, provider, mark_calls, mark_retries)
            return _pause_run(
                run, run_id, badge="blocked",
                title="Resolve the blocking questions first.",
                questions=_blocker_questions(rule_blockers),
            )
        decision = {"badge": "blocked", "title": "Resolve the blocking questions first."}
        detail = f"{len(blockers)} blocking questions asked"
        meta = "stopped before decision"
    elif _dental_flag(receipt, cert):
        # T6: dental treatment is flagged for a reviewer, never decided.
        detail = f"dental flag: {_dental_flag(receipt, cert)}"
        decision = {"badge": "needs_review",
                    "title": ("Flagged for a reviewer: dental treatment "
                              "is never decided automatically.")}
        meta = "stopped before decision"
        stop_questions = [{
            "question": ("This claim involves dental treatment "
                         f"({detail}); what should the reviewer check?"),
            "why_needed": ("No payout rule exists for dental care; "
                           "a reviewer decides, the engine never does."),
        }]
    elif eligibility["outcome"] in ("nhi_member", "traveller_abroad"):
        # C3: same bar as the agent path (tool_adjudicate): a Korean claim
        # without a copay rate is stopped, never adjudicated.
        if receipt.get("country") == "KR" and copay_rate_from_bill(
                receipt.get("kr_bill")) is None:
            decision = {"badge": "needs_manual_check",
                        "title": "Human review: the copay rate is missing."}
            detail = "stopped: KR receipt without cells 1 and 2"
            meta = "stopped before decision"
            stop_questions = [{
                "question": "What are receipt cells 1 and 2 (copay amounts)?",
                "why_needed": "The copay rate (cell 1 / (cell 1 + cell 2)) "
                              "is required to adjudicate a Korean claim.",
            }]
        else:
            # H2: a byte-matched sample runs on its own policy; every other
            # run needs the product the user chose — never a declared
            # scenario's policy.
            from claimlens.engine import build_inputs_for_product, product_catalog

            catalog = product_catalog()
            chosen = "" if matched else person.get("product", "")
            if not matched and chosen not in catalog:
                run["tokens_total"] = tokens_total
                _bank_finish_spend(run, provider, mark_calls, mark_retries)
                known = ", ".join(sorted(catalog)) or "none"
                return _pause_run(
                    run, run_id, badge="need_product",
                    title="Choose an insurance product to continue.",
                    questions=[{
                        "id": "product",
                        "question": "Which insurance product covers this claim?",
                        "why_needed": ("The engine prices against the chosen "
                                       f"product's demo terms. Known: {known}."),
                    }],
                )
            if not neo4j_up():
                run["tokens_total"] = tokens_total
                _bank_finish_spend(run, provider, mark_calls, mark_retries)
                return _pause_run(
                    run, run_id, badge="engine_unreachable",
                    title="Neo4j is down; no decision made.",
                    questions=[{
                        "question": ("The engine is unreachable. Start Neo4j "
                                     "and resend to retry — no new reading is needed."),
                        "why_needed": ("The verified reading is kept; "
                                       "retrying reuses it."),
                    }],
                )
            if matched:
                inputs = build_inputs(matched, "photo", reading)
                note = "live engine call, not cached"
            else:
                claim_id = f"live-{run_id[:8]}" if run_id else "live-upload"
                inputs = build_inputs_for_product(chosen, claim_id, reading)
                note = f"{chosen} chosen by user (demo terms); live engine call, not cached"
                if declared and declared != matched:
                    note += f"; declared {declared} shown for reference only"
            output = live_adjudicate(inputs)
            decision = {"badge": output["decision"], "title": f"{output['amount']:,} KRW"}
            detail = f"{output['decision']} {output['amount']:,} KRW"
            meta = note
    elif eligibility["outcome"] == "not_member_or_unknown" and matched:
        from claimlens.claimpack import build_pack_from_reading
        from claimlens.letter import build_letter

        try:
            pack = build_pack_from_reading(reading, provider, matched, "photo")
        except ValueError as exc:
            decision = {"badge": "needs_manual_check",
                        "title": f"Human review: {exc}"}
            detail = "pack refused: receipt checks failed"
            meta = "stopped before decision"
        else:
            letter = build_letter(matched, "photo", pack, provider)
            decision = {"badge": "claim_pack",
                        "title": "Claim Pack built (sample-matched).",
                        "letter": letter["text"], "letter_source": letter["source"]}
            detail = f"{len(pack['items'])} lines, total {pack['total_krw']:,} KRW"
            meta = "sample-matched pack"
    else:
        decision = {"badge": "needs_review", "title": "Human review: no decision path."}
        detail = eligibility["basis"]
        meta = "deterministic"
    decision["note"] = note
    _step(steps, "decision", "Decision", detail, meta, time.monotonic() - started)
    finish_spend = _fresh_spend(provider.calls[mark_calls:])
    finish_retries = getattr(provider, "retries_429", 0) - mark_retries

    response: dict[str, Any] = {
        "steps": steps,
        "result": decision,
        "tokens_total": tokens_total,
        "cost_usd": run.get("cost_usd", 0.0) + finish_spend,
        "retries_429": run.get("retries_429", 0) + finish_retries,
        "matched_sample": matched,
        "scenario": declared,
        "questions": [
            {"question": f.get("question", ""), "why_needed": f.get("why_needed", "")}
            for f in blockers
        ] + stop_questions,
    }
    if run.get("merge") is not None:
        response["merge"] = run["merge"]
    return response


def run_continue(
    run_id: str,
    person: dict[str, Any] | None = None,
    scenario: str | None = None,
    resolutions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Answer a paused run's questions; finishes with no new reading call.

    resolutions answers gate picks (H7) or blocker picks/notes (H8) by
    question id; person/scenario merge as before under the same run_id.
    """
    from claimlens.engine import load_scenarios

    if not isinstance(run_id, str) or run_id not in _RUNS:
        raise ValueError("Unknown or expired run; drop the photos again.")
    run = _RUNS[run_id]
    scenarios, _ = load_scenarios()
    declared = check_scenario(scenario, scenarios)
    if declared:
        run["scenario"] = declared
    merged = dict(run["person"])
    for key, value in check_person(person).items():
        if value is None or (isinstance(value, str) and not value.strip()):
            merged.pop(key, None)
        else:
            merged[key] = value
    run["person"] = merged
    answers = _check_resolutions(resolutions)
    if run.get("gate"):
        if not answers:
            gate = run["gate"]
            return _pause_run(
                run, run_id, badge="needs_manual_check",
                title=("Human review: two reads disagreed — "
                       "pick the printed value for each field."),
                questions=gate_questions(gate["diffs"]),
            )
        return _continue_gate(run, run_id, answers)
    if run.get("blockers"):
        if not answers:
            return _pause_run(
                run, run_id, badge="blocked",
                title="Resolve the blocking questions first.",
                questions=_blocker_questions(run["blockers"]),
            )
        return _continue_blockers(run, run_id, answers)
    if answers:
        raise ValueError("This run has no pending choices to answer.")
    if missing_facts(merged):
        return _pause_run(run, run_id)
    del _RUNS[run_id]
    return _finish_run(live_provider(), run, run_id)


def _continue_gate(run: dict[str, Any], run_id: str,
                   answers: dict[str, Any]) -> dict[str, Any]:
    """Apply gate picks; re-pause when they fail checks, else move on."""
    _resolve_gate(run, answers)
    if run["_resolve_failing"]:
        names = ", ".join(run["_resolve_failing"])
        return _pause_run(
            run, run_id, badge="needs_manual_check",
            title=(f"Those picks fail the receipt checks ({names}); "
                   "pick again."),
            questions=gate_questions(run["gate"]["diffs"]),
        )
    picks = run["_resolve_picks"]
    if run.get("multi"):
        try:
            _adopt_multi_resolved(run)
        except ValueError as exc:
            # The picks pass per-photo checks but cannot merge; the gate
            # stays so the person can pick again under the same run_id.
            return _pause_run(
                run, run_id, badge="needs_manual_check",
                title=f"Those picks cannot merge ({exc}); pick again.",
                questions=gate_questions(run["gate"]["diffs"]),
            )
    else:
        run["reading"] = {"documents": run["gate_resolved"][None]}
    run["readings_changed"] = True
    for key in ("gate", "gate_resolved", "_resolve_picks", "_resolve_failing"):
        run.pop(key, None)
    _step(run["steps"], "resolve", "Resolve",
          "person chose: " + "; ".join(picks), "person-confirmed", 0.0)
    if missing_facts(run["person"]):
        return _pause_run(run, run_id)
    del _RUNS[run_id]
    return _finish_run(live_provider(), run, run_id)


def _continue_blockers(run: dict[str, Any], run_id: str,
                       answers: dict[str, Any]) -> dict[str, Any]:
    """Apply blocker picks (validated against the quotes) and notes (H8)."""
    pending = run.get("blockers") or []
    kinds = {f["kind"] for f in pending}
    resolved = dict(run.get("resolved_blockers", {}))
    notes = dict(run.get("blocker_notes", {}))
    for key, value in answers.items():
        if not key.startswith("blocker:") or key[8:] not in kinds:
            raise ValueError(f"Unknown blocker choice {key!r}.")
        kind = key[8:]
        if isinstance(value, dict):
            note = value.get("note", "")
            if not isinstance(note, str) or not note.strip():
                raise ValueError(f"Answer {key!r} needs a note.")
            notes[kind] = note.strip()
            continue
        if value not in ("receipt", "cert"):
            raise ValueError(f"Choice {key!r} must be 'receipt' or 'cert'.")
        finding = next(f for f in pending if f["kind"] == kind)
        resolved[kind] = {"pick": value,
                          "value": finding[f"quote_{value}"]}
    run["resolved_blockers"] = resolved
    run["blocker_notes"] = notes
    run["resolved"] = {**run.get("resolved", {}),
                       "blockers": resolved, "notes": notes}
    remaining = [f for f in pending if f["kind"] not in resolved]
    run["blockers"] = remaining
    if remaining:
        return _pause_run(
            run, run_id, badge="blocked",
            title="Resolve the blocking questions first.",
            questions=_blocker_questions(remaining),
        )
    if missing_facts(run["person"]):
        return _pause_run(run, run_id)
    del _RUNS[run_id]
    return _finish_run(live_provider(), run, run_id)


def _blocker_questions(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """H8: each rule blocker as a pick (receipt/cert quotes) plus a note box."""
    out = []
    for finding in blockers:
        kind = finding["kind"]
        out.append({
            "id": f"blocker:{kind}",
            "question": finding.get("question", ""),
            "why_needed": finding.get("why_needed", ""),
            "options": [
                {"id": "receipt", "label": f"receipt: {finding['quote_receipt']}",
                 "source": f"receipt ({kind})"},
                {"id": "cert", "label": f"certificate: {finding['quote_cert']}",
                 "source": f"certificate ({kind})"},
            ],
            "note": True,
        })
    return out


def _host_ok(host: str, port: int) -> bool:
    """Same-machine allow-list shared by GET and POST (S1)."""
    hosts = (f"127.0.0.1:{port}", f"localhost:{port}")
    return host.strip().lower() in hosts


def route_get(path: str, *, host: str = "", port: int = 0) -> tuple[int, bytes, str]:
    """Pure GET routing: status, body bytes, media type. No sockets.

    S1: the Host allow-list matches POST, and backslash, colon or NUL
    anywhere in the path is rejected before any path join (UNC/drive/NUL).
    Direct callers that pass no host skip the Host check; do_GET always
    passes the real headers, so the HTTP boundary is always checked.
    """
    if host and not _host_ok(host, port):
        return 403, b"bad host", "text/plain"
    if path == "/api/health":
        return 200, json.dumps({"ok": True, "mode": "live"}).encode("utf-8"), "application/json"
    target = unquote(path)
    if "\\" in target or ":" in target or "\0" in target:
        return 400, b"bad path", "text/plain"
    if target in ("", "/"):
        target = "/index.html"
    root = repo_root()
    resolved = (root / target.lstrip("/")).resolve()
    allowed = resolved.is_relative_to(root) and (
        resolved.name == "index.html"
        or resolved.is_relative_to(root / "docs")
        or resolved.is_relative_to(root / "samples")
    )
    if not allowed or not resolved.is_file():
        code = 404 if allowed else 403
        return code, json.dumps({"error": "not found"}).encode("utf-8"), "application/json"
    media = "application/octet-stream"
    if resolved.suffix == ".html":
        media = "text/html"
    elif resolved.suffix == ".wav":
        media = "audio/wav"
    elif resolved.suffix in (".jpg", ".jpeg"):
        media = "image/jpeg"
    elif resolved.suffix == ".png":
        media = "image/png"
    return 200, resolved.read_bytes(), media


def route_post(
    path: str, raw: bytes, declared: int, headers: dict[str, str], port: int
) -> tuple[int, dict[str, Any]]:
    """Pure POST routing: status plus JSON payload. No sockets.

    Spend guard: only same-origin JSON posts from this machine reach
    the pipeline. The Host check also blocks DNS rebinding.
    """
    if path != "/api/run":
        return 404, {"error": "not found"}
    if not _host_ok(headers.get("host", ""), port):
        return 403, {"error": "forbidden host"}
    media = headers.get("content_type", "").split(";")[0].strip().lower()
    if media != "application/json":
        return 415, {"error": "Content-Type must be application/json."}
    origin = (headers.get("origin") or "").strip().lower()
    allowed = (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
    if origin and origin not in allowed:
        return 403, {"error": "cross-origin posts are forbidden"}
    if declared > MAX_BODY_BYTES:
        return 413, {"error": "Uploads exceed the 10 MB limit."}
    try:
        body = json.loads(raw.decode("utf-8"))
        if body.get("run_id"):
            result = run_continue(body["run_id"], body.get("person"),
                                    body.get("scenario"), body.get("resolutions"))
        else:
            result = run_live(body.get("images", []), body.get("person"), body.get("scenario"))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return 400, {"error": str(exc)}
    except RuntimeError as exc:
        return 503, {"error": str(exc)}
    return 200, result


class Handler(BaseHTTPRequestHandler):
    server_version = "ClaimLensLive/0.1"

    def log_message(self, *args: Any) -> None:
        pass

    def _send(self, status: int, body: bytes, media: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")

    def do_GET(self) -> None:
        host = self.headers.get("Host") or ""
        status, body, media = route_get(urlparse(self.path).path, host=host,
                                        port=self.server.server_port)
        if media == "application/json":
            self._send_json(status, json.loads(body.decode("utf-8")))
        else:
            self._send(status, body, media)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            declared = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            declared = 0
        if path == "/api/run" and declared <= MAX_BODY_BYTES:
            raw = self.rfile.read(declared) if declared else b""
        else:
            raw = b""
        headers = {
            "host": self.headers.get("Host") or "",
            "content_type": self.headers.get("Content-Type") or "",
            "origin": self.headers.get("Origin") or "",
        }
        status, payload = route_post(path, raw, declared, headers, self.server.server_port)
        self._send_json(status, payload)


def serve_forever(port: int = 8000) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print(f"ClaimLens live on http://127.0.0.1:{server.server_port} (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def start_background(port: int = 0) -> ThreadingHTTPServer:
    """Ephemeral server for tests; caller must shutdown() + server_close()."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
