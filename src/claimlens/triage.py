"""Messy bundle triage: sort a shuffled pile of claim photos.

One Muse Spark strict-schema call classifies every page in input
order (kind plus identity copied from the page). Code then groups
pages into the claim (majority patient + service date), drops
unrelated pages with a reason, merges duplicates (same kind,
identity, and total), and names missing documents from the expected
checklist. Totals are compared as copied strings — never computed.
Identities are normalised before grouping: bracketed transliterations
go, case folds, spaces and punctuation collapse, name tokens compare
as a set, and dates match when visit periods overlap.
"""

import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from claimlens.schema import strict_schema_of

PageKind = Literal["receipt", "itemized_statement", "medical_certificate", "unrelated"]

EXPECTED: tuple[str, ...] = ("receipt", "itemized_statement", "medical_certificate")

LABELS = {
    "receipt": "receipt",
    "itemized_statement": "itemized statement",
    "medical_certificate": "medical certificate",
    "unrelated": "unrelated page",
}

TRIAGE_INSTRUCTIONS = (
    "You sort a pile of claim photos. Classify EVERY image in input order, "
    "one entry per image. kind is receipt, itemized_statement, "
    "medical_certificate, or unrelated (not a claim document at all). Copy "
    "the patient name, service date, and total exactly as printed, or null "
    "when not shown. reason is one line saying what the page is."
)


class PageClass(BaseModel):
    kind: PageKind = Field(description="What the page is.")
    patient: str | None = Field(default=None, description="Patient name as printed.")
    service_date: str | None = Field(default=None, description="Service date as printed.")
    total: str | None = Field(default=None, description="Total as printed, with currency.")
    reason: str = Field(description="One line saying what the page is.")


class PageClassSet(BaseModel):
    pages: list[PageClass] = Field(description="One entry per input image, in order.")


def triage_schema() -> dict[str, Any]:
    return strict_schema_of(PageClassSet)


def classify_pages(images: list[Path], provider: Any) -> list[dict[str, Any]]:
    """One strict-schema call classifying every page in input order."""
    for image in images:
        if not image.is_file():
            raise FileNotFoundError(f"Not an image file: {image}")
    result = provider.read_documents(
        list(images), TRIAGE_INSTRUCTIONS, triage_schema(), PageClassSet
    )
    pages = result.get("pages", [])
    if len(pages) != len(images):
        raise ValueError(
            f"Classifier returned {len(pages)} entries for {len(images)} images."
        )
    return pages


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    folded = " ".join(re.sub(r"[^\w\s]", " ", value).split()).casefold()
    return folded or None


def _name_tokens(value: str | None) -> frozenset[str]:
    """Name tokens as a set: bracketed transliterations stripped first."""
    if not value:
        return frozenset()
    bare = re.sub(r"\s*[\(\[][^\]\)]*[\)\]]", "", value)
    return frozenset(_norm(bare).split()) if _norm(bare) else frozenset()


def _date_interval(value: str | None) -> tuple[date, date] | None:
    """(start, end) visit period from a printed date or range, else None."""
    if not value:
        return None
    days = []
    for year, month, day in re.findall(r"(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})", value):
        try:
            days.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    if not days:
        return None
    return (min(days), max(days))


def _dates_match(first: str | None, second: str | None) -> bool:
    """Visit periods overlap; unreadable dates fall back to string equality."""
    span_a, span_b = _date_interval(first), _date_interval(second)
    if span_a is not None and span_b is not None:
        return span_a[0] <= span_b[1] and span_b[0] <= span_a[1]
    return _norm(first) == _norm(second)


def triage_pages(
    classes: list[dict[str, Any]], expected: tuple[str, ...] = EXPECTED
) -> dict[str, Any]:
    """Group, drop, merge, and name missing. Pure; no model calls."""
    tokens = [_name_tokens(page.get("patient")) for page in classes]
    intervals = [_date_interval(page.get("service_date")) for page in classes]
    keys = [
        (tokens[index], intervals[index] or ("raw", _norm(page.get("service_date"))))
        if page.get("kind") != "unrelated"
        else None
        for index, page in enumerate(classes)
    ]
    claim = Counter(key for key in keys if key is not None).most_common(1)
    claim_key = claim[0][0] if claim else None
    rep = next((i for i, key in enumerate(keys) if key is not None and key == claim_key), None)
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen: dict[tuple, int] = {}
    merged: list[dict[str, int]] = []
    for index, page in enumerate(classes):
        kind = page.get("kind", "unrelated")
        if kind == "unrelated":
            dropped.append({"index": index, "reason": f"unrelated: {page.get('reason', '')}"})
            continue
        same_claim = keys[index] == claim_key or (
            rep is not None
            and tokens[index] == tokens[rep]
            and _dates_match(page.get("service_date"), classes[rep].get("service_date"))
        )
        if not same_claim:
            patient = page.get("patient") or "unknown patient"
            when = page.get("service_date") or "no date"
            dropped.append(
                {"index": index, "reason": f"belongs to {patient} ({when}), not this claim"}
            )
            continue
        identity = (kind, tokens[index], keys[index][1], _norm(page.get("total")))
        if identity in seen:
            merged.append({"kept_index": seen[identity], "from_index": index})
            continue
        seen[identity] = index
        entry: dict[str, Any] = {"index": index, "kind": kind}
        if rep is not None and (page.get("patient") or "") != (classes[rep].get("patient") or ""):
            entry["note"] = f"name written differently on the {LABELS[kind]}"
        kept.append(entry)
    kept_kinds = {entry["kind"] for entry in kept}
    missing = [f"{LABELS[kind]} missing" for kind in expected if kind in LABELS and kind not in kept_kinds]
    return {
        "claim": {
            "patient": classes[rep].get("patient") if rep is not None else None,
            "service_date": classes[rep].get("service_date") if rep is not None else None,
        },
        "kept": kept,
        "dropped": dropped,
        "merged": merged,
        "missing": missing,
    }


def triage_bundle(
    images: list[Path | str],
    provider: Any,
    expected: tuple[str, ...] = EXPECTED,
) -> dict[str, Any]:
    """Classify the pile, then triage it. File names ride along per index."""
    paths = [Path(image) for image in images]
    classes = classify_pages(paths, provider)
    result = triage_pages(classes, expected)
    result["pages"] = [
        {"index": index, "file": path.name, **page}
        for index, (path, page) in enumerate(zip(paths, classes, strict=True))
    ]
    return result


def render_report(result: dict[str, Any]) -> str:
    """Short human-readable triage report."""
    lines = []
    for page in result.get("pages", []):
        lines.append(f"[{page['index']}] {page['file']}: {page.get('kind')}")
    lines.append("")
    kept_bits = []
    for entry in result.get("kept", []):
        bit = f"[{entry['index']}] {entry['kind']}"
        if entry.get("note"):
            bit += f" ({entry['note']})"
        kept_bits.append(bit)
    lines.append(f"kept: {', '.join(kept_bits) or 'none'}")
    for drop in result.get("dropped", []):
        lines.append(f"dropped [{drop['index']}]: {drop['reason']}")
    for merge in result.get("merged", []):
        lines.append(f"merged [{merge['from_index']}] into [{merge['kept_index']}] (duplicate)")
    for gap in result.get("missing", []):
        lines.append(f"missing: {gap}")
    return "\n".join(lines)
