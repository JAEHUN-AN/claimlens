"""Cross-document consistency: do the receipt and certificate belong together?

Two layers. (1) Deterministic exact checks compare names, birth dates,
visit dates, visit type, and hospital across the two readings. (2) A
Muse Spark strict-schema pass compares what rules cannot: billed lines
vs certificate diagnoses, diagnosis vs billed categories, dates across
documents. Every Spark finding carries a quote from EACH document, and
code drops any finding whose quotes are not found in the readings, so
no invented evidence survives. Wording stays about paperwork
consistency — never clinical judgement, never "fraud".
"""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from claimlens.schema import strict_schema_of

Severity = Literal["blocker", "check"]

BUNDLES: dict[str, dict[str, Any]] = {
    "A": {
        "receipt": ("A_niseko_wrist", "photo"),
        "cert": ("A_niseko_wrist", "photo"),
        "expected": [],
    },
    "S2": {
        "receipt": ("S2_seoul_worker_bronchitis", "photo"),
        "cert": ("S2_seoul_worker_bronchitis", "photo"),
        "expected": [],
    },
    "S3": {
        "receipt": ("S3_us_tourist_hip_fracture", "photo"),
        "cert": ("S3_us_tourist_hip_fracture", "photo"),
        "expected": [],
    },
    "S2r-S3c": {
        "receipt": ("S2_seoul_worker_bronchitis", "photo"),
        "cert": ("S3_us_tourist_hip_fracture", "photo"),
        "expected": ["patient_name", "visit_date", "visit_type"],
        "note": "birth_date is not printed on the S2 receipt, so it cannot mismatch.",
    },
    "Ar-Cc": {
        "receipt": ("A_niseko_wrist", "photo"),
        "cert": ("C_newyork_panic", "photo"),
        "expected": ["patient_name", "birth_date", "visit_date"],
    },
    "S2r-Ac": {
        "receipt": ("S2_seoul_worker_bronchitis", "photo"),
        "cert": ("A_niseko_wrist", "photo"),
        "expected": ["patient_name", "visit_date"],
        "note": "birth_date is not printed on the S2 receipt, so it cannot mismatch.",
    },
}

BANNED_WORDS = ("fraud",)


class Finding(BaseModel):
    kind: str = Field(description="Machine kind, e.g. patient_name or billed_not_described.")
    severity: Severity = Field(description="blocker stops the claim; check is a note.")
    quote_receipt: str = Field(description="Exact words from the receipt reading.")
    quote_cert: str = Field(description="Exact words from the certificate reading.")
    reason: str = Field(description="One line about paperwork consistency only.")


class FindingSet(BaseModel):
    findings: list[Finding] = Field(description="Empty when the documents agree.")


def findings_schema() -> dict[str, Any]:
    return strict_schema_of(FindingSet)


def bundle_reading(bundle_id: str) -> dict[str, dict[str, Any]]:
    """Receipt reading from one sample, certificate reading from another.

    Each document keeps the reading recorded from its own images; mixing
    simulates a claim bundle whose documents disagree.
    """
    from claimlens.engine import replay_reading

    try:
        spec = BUNDLES[bundle_id]
    except KeyError:
        raise ValueError(f"Unknown bundle {bundle_id!r}; want one of {sorted(BUNDLES)}.") from None
    receipt_sample, receipt_variant = spec["receipt"]
    cert_sample, cert_variant = spec["cert"]
    receipt = replay_reading(receipt_sample, receipt_variant)["documents"][0]
    cert = replay_reading(cert_sample, cert_variant)["documents"][1]
    return {"receipt": receipt, "cert": cert}


def _pii(doc: dict[str, Any], kind: str) -> str:
    for item in doc.get("pii", []):
        if item.get("kind") == kind:
            return item.get("value") or ""
    return ""


def _norm_name(value: str) -> str:
    no_parens = re.sub(r"\([^)]*\)", " ", value)
    return re.sub(r"\s+", " ", no_parens).strip().lower()


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _receipt_dates(receipt: dict[str, Any]) -> set[str]:
    bill = receipt.get("kr_bill") or {}
    return {
        d
        for d in (receipt.get("service_date"), bill.get("period_from"), bill.get("period_to"))
        if d
    }


def _cert_dates(cert: dict[str, Any]) -> set[str]:
    return {d for d in (cert.get("service_date"),) if d}


def _visit_label(doc: dict[str, Any]) -> str:
    return "inpatient" if doc.get("inpatient") else "outpatient"


_QUESTIONS = {
    "patient_name": (
        "The receipt and the certificate name different patients. Which patient is this claim for?",
        "A claim needs exactly one patient; the documents disagree.",
    ),
    "birth_date": (
        "The receipt and the certificate show different birth dates. Which one is right?",
        "Identity must match across documents before the claim can proceed.",
    ),
    "visit_date": (
        "The receipt and the certificate show non-overlapping visit dates. Which visit is this claim for?",
        "The billed visit and the certified visit must be the same one.",
    ),
    "visit_type": (
        "One document says outpatient and the other says inpatient. Which was it?",
        "Outpatient and inpatient visits are claimed differently.",
    ),
}


def deterministic_findings(receipt: dict[str, Any], cert: dict[str, Any]) -> list[dict[str, Any]]:
    """Exact comparisons; code-built quotes from the compared fields."""
    findings: list[dict[str, Any]] = []

    def add(kind: str, severity: str, quote_receipt: str, quote_cert: str, reason: str) -> None:
        finding: dict[str, Any] = {
            "kind": kind,
            "severity": severity,
            "layer": "rule",
            "quote_receipt": quote_receipt,
            "quote_cert": quote_cert,
            "reason": reason,
        }
        if severity == "blocker":
            finding["question"], finding["why_needed"] = _QUESTIONS[kind]
        findings.append(finding)

    r_name, c_name = _pii(receipt, "name"), _pii(cert, "name")
    if r_name and c_name and _norm_name(r_name) != _norm_name(c_name):
        add("patient_name", "blocker", r_name, c_name,
            f"Receipt names {r_name} but the certificate names {c_name}.")
    r_dob, c_dob = _pii(receipt, "date_of_birth"), _pii(cert, "date_of_birth")
    if r_dob and c_dob and r_dob.strip() != c_dob.strip():
        add("birth_date", "blocker", r_dob, c_dob,
            f"Birth dates differ: {r_dob} vs {c_dob}.")
    r_dates, c_dates = _receipt_dates(receipt), _cert_dates(cert)
    if r_dates and c_dates and not (r_dates & c_dates):
        add("visit_date", "blocker", ", ".join(sorted(r_dates)), ", ".join(sorted(c_dates)),
            f"Visit dates do not overlap: receipt {', '.join(sorted(r_dates))}; "
            f"certificate {', '.join(sorted(c_dates))}.")
    if bool(receipt.get("inpatient")) != bool(cert.get("inpatient")):
        r_label, c_label = _visit_label(receipt), _visit_label(cert)
        add("visit_type", "blocker", r_label, c_label,
            f"Receipt is {r_label} but the certificate is {c_label}.")
    r_hosp, c_hosp = receipt.get("provider_name") or "", cert.get("provider_name") or ""
    r_norm, c_norm = _norm_text(r_hosp), _norm_text(c_hosp)
    if r_norm and c_norm and r_norm != c_norm and r_norm not in c_norm and c_norm not in r_norm:
        add("hospital", "check", r_hosp, c_hosp, f"Hospitals differ: {r_hosp} vs {c_hosp}.")
    return findings


SPARK_PREAMBLE = """You compare two hospital documents (a receipt and a medical certificate) \
from ONE claim bundle for paperwork consistency. The verified readings are \
below as JSON; treat them as the only evidence.
Report ONLY inconsistencies between the documents. Kinds: billed_not_described \
(a billed line or category the certificate never mentions), \
described_not_billed, diagnosis_vs_department (a diagnosis label beside billed \
categories that do not belong with it on paper), prose_date (a date in one \
document contradicted by the other).
Rules:
- Both quotes MUST be copied character-for-character from the reading text \
below. Never quote what is not there.
- Wording is about paperwork consistency only. Never give clinical judgement, \
never write "fraud".
- Do not repeat the rule findings already listed below.
- Severity blocker only for identity or date contradictions; everything else \
is check.
- Empty findings list when the documents agree."""


def spark_instructions(
    receipt: dict[str, Any], cert: dict[str, Any], ruled: list[dict[str, Any]]
) -> str:
    ruled_kinds = sorted({f["kind"] for f in ruled})
    body = {
        "rule_findings_already_reported": ruled_kinds,
        "receipt_reading": receipt,
        "certificate_reading": cert,
    }
    return f"{SPARK_PREAMBLE}\nEvidence:\n{json.dumps(body, ensure_ascii=False, sort_keys=True)}"


def quotes_found(finding: dict[str, Any], receipt: dict[str, Any], cert: dict[str, Any]) -> bool:
    """Both quotes occur verbatim (modulo case/whitespace) in their reading."""
    receipt_text = _norm_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    cert_text = _norm_text(json.dumps(cert, ensure_ascii=False, sort_keys=True))
    quote_r = _norm_text(finding.get("quote_receipt") or "")
    quote_c = _norm_text(finding.get("quote_cert") or "")
    return bool(quote_r) and bool(quote_c) and quote_r in receipt_text and quote_c in cert_text


def _banned(finding: dict[str, Any]) -> bool:
    text = " ".join(
        str(finding.get(key) or "") for key in ("quote_receipt", "quote_cert", "reason")
    ).lower()
    return any(word in text for word in BANNED_WORDS)


def spark_findings(
    receipt: dict[str, Any], cert: dict[str, Any], provider: Any
) -> tuple[list[dict[str, Any]], int]:
    """Strict-schema pass; returns verified findings plus dropped count."""
    ruled = deterministic_findings(receipt, cert)
    draft = provider.write(spark_instructions(receipt, cert, ruled), findings_schema(), FindingSet)
    kept: list[dict[str, Any]] = []
    dropped = 0
    for item in draft.get("findings", []):
        if not quotes_found(item, receipt, cert) or _banned(item):
            dropped += 1
            continue
        kept.append({**item, "layer": "spark"})
    return kept, dropped


def check_consistency(bundle_id: str, provider: Any) -> dict[str, Any]:
    """Both layers plus quote verification; blockers stop the claim."""
    from claimlens.supervision import verify_claims

    docs = bundle_reading(bundle_id)
    ruled = deterministic_findings(docs["receipt"], docs["cert"])
    sparked, dropped = spark_findings(docs["receipt"], docs["cert"], provider)
    verdict = verify_claims(
        [
            {
                "statement": f["reason"],
                "quote": f"Receipt: {f['quote_receipt']} | Certificate: {f['quote_cert']}",
            }
            for f in sparked
        ],
        provider,
    )
    sparked = [f for f, ok in zip(sparked, verdict["verdicts"], strict=True) if ok]
    findings = ruled + sparked
    blockers = [f for f in findings if f["severity"] == "blocker"]
    spec = BUNDLES[bundle_id]
    return {
        "bundle": bundle_id,
        "receipt": {"sample": spec["receipt"][0], "variant": spec["receipt"][1]},
        "cert": {"sample": spec["cert"][0], "variant": spec["cert"][1]},
        "findings": findings,
        "blockers": [
            {"kind": f["kind"], "question": f.get("question", ""), "why_needed": f.get("why_needed", "")}
            for f in blockers
        ],
        "stopped": bool(blockers),
        "dropped_quotes": dropped,
        "unverified_dropped": verdict["dropped"],
        "provider": provider.name,
        "model": provider.model,
        "calls": [vars(c) for c in provider.calls],
    }


def score_bundle(bundle_id: str, found_kinds: list[str]) -> dict[str, Any]:
    """Precision/recall of deterministic blocker kinds against ground truth."""
    expected = set(BUNDLES[bundle_id].get("expected", []))
    found = set(found_kinds)
    tp = len(expected & found)
    fp = len(found - expected)
    fn = len(expected - found)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return {
        "bundle": bundle_id,
        "expected": sorted(expected),
        "found": sorted(found),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
    }


def eval_all(provider: Any) -> list[dict[str, Any]]:
    """Run every bundle; Spark blockers beyond ground truth are reported extra."""
    rows = []
    for bundle_id in BUNDLES:
        result = check_consistency(bundle_id, provider)
        ruled_kinds = [f["kind"] for f in result["findings"] if f["layer"] == "rule" and f["severity"] == "blocker"]
        row = score_bundle(bundle_id, ruled_kinds)
        spark_blockers = [f["kind"] for f in result["findings"] if f["layer"] == "spark" and f["severity"] == "blocker"]
        spark_checks = [f["kind"] for f in result["findings"] if f["layer"] == "spark" and f["severity"] == "check"]
        row["spark_blockers"] = spark_blockers
        row["spark_checks"] = spark_checks
        row["dropped_quotes"] = result["dropped_quotes"]
        rows.append(row)
    return rows


def format_markdown(rows: list[dict[str, Any]]) -> str:
    def cell(value: list[str]) -> str:
        if not value:
            return "-"
        counts: dict[str, int] = {}
        for kind in value:
            counts[kind] = counts.get(kind, 0) + 1
        return ", ".join(f"{kind} (×{n})" if n > 1 else kind for kind, n in counts.items())

    lines = [
        "| bundle | expected blockers | found blockers | precision | recall | spark blockers | spark checks | dropped |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['bundle']} | {cell(row['expected'])} | {cell(row['found'])} "
            f"| {row['precision']:.3f} | {row['recall']:.3f} "
            f"| {cell(row['spark_blockers'])} | {cell(row['spark_checks'])} | {row['dropped_quotes']} |"
        )
    lines += [
        "",
        "Notes:",
        "",
        "- Precision/recall cover deterministic blocker kinds only; Spark narrative",
        "  findings have no per-kind ground truth and are listed separately.",
        "- birth_date cannot mismatch where a receipt prints no birth date (S2).",
    ]
    return "\n".join(lines) + "\n"
