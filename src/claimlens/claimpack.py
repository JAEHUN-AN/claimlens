"""English Claim Pack for visitors without an applicable policy (SPEC 3.6).

Built only for `not_member_or_unknown` cases. The model translates row
labels; every amount, code, and date is copied by code from the reading.
"""

import html
from typing import Any

from pydantic import BaseModel, Field

from claimlens.checks import all_passed, check_kr_bill, check_kr_lines
from claimlens.codes import DISCLAIMER as CODE_DISCLAIMER
from claimlens.codes import convert_diagnosis
from claimlens.schema import strict_schema_of

POLICY_LINE = "We do not have your policy, so this is not a coverage decision."
TRANSLATION_NOTE = "Draft translation of labels; not a certified translation."
PII_CHECK_MARK = "check against your passport/ID"

CHECKLIST = [
    "English medical certificate: request it while still under care.",
    "Itemized statement (separate from the receipt): only the patient can be issued one.",
    "Your insurer's own physician statement form, if it has one.",
]

GENERIC_DEADLINE = "Check your own policy for notice and filing deadlines."


class LabelPair(BaseModel):
    ko: str = Field(description="Korean label, copied exactly.")
    en: str = Field(description="Short English translation.")


class LabelTranslation(BaseModel):
    labels: list[LabelPair] = Field(description="One pair per input label.")


def labels_schema() -> dict[str, Any]:
    return strict_schema_of(LabelTranslation)


LABELS_PREAMBLE = """Translate Korean hospital charge labels into short English.
Copy each Korean label exactly into ko and give a plain English equivalent in
en. Translate only; never add amounts, codes, or explanations."""


def translate_labels(labels: list[str], provider: Any) -> dict[str, str]:
    """One strict-schema call; every input label must come back translated."""
    listed = "\n".join(f"- {label}" for label in labels)
    draft = provider.write(
        f"{LABELS_PREAMBLE}\nLabels:\n{listed}", labels_schema(), LabelTranslation
    )
    table = {pair["ko"]: pair["en"] for pair in draft.get("labels", [])}
    missing = [label for label in labels if label not in table]
    if missing:
        raise ValueError(f"Untranslated labels: {missing}.")
    return table


def _pii_of(docs: list[dict[str, Any]], kind: str) -> str:
    for doc in docs:
        for item in doc.get("pii", []):
            if item.get("kind") == kind and item.get("value"):
                return item["value"]
    return ""


def _doc_label(doc: dict[str, Any]) -> str:
    return {"receipt": "receipt", "medical_certificate": "certificate"}.get(
        doc.get("doc_type", ""), doc.get("doc_type", "document")
    )


def pii_conflicts(docs: list[dict[str, Any]]) -> dict[str, list[list[str]]]:
    """Kinds whose value differs between documents: {kind: [[where, value]]}."""
    seen: dict[str, list[list[str]]] = {}
    for doc in docs:
        where = _doc_label(doc)
        for item in doc.get("pii", []):
            kind, value = item.get("kind", ""), item.get("value", "")
            if not kind or not value:
                continue
            entries = seen.setdefault(kind, [])
            if [where, value] not in entries:
                entries.append([where, value])
    return {k: v for k, v in seen.items() if len({value for _, value in v}) > 1}


def _pii_line(label: str, value: str, conflict: list[list[str]] | None) -> str:
    if not value:
        return f"- {label}: -"
    if conflict:
        readings = " / ".join(f"{v} ({w})" for w, v in conflict)
        return f"- {label}: {readings} — differs between documents; {PII_CHECK_MARK}"
    return f"- {label}: {value} — {PII_CHECK_MARK}"


def html_pii(label: str, value: str, conflict: list[list[str]] | None) -> str:
    if not value:
        return f"{label}: -"
    if conflict:
        readings = " / ".join(
            f"{html.escape(v)} ({html.escape(w)})" for w, v in conflict
        )
        return f"{label}: {readings} — differs between documents; {PII_CHECK_MARK}"
    return f"{label}: {html.escape(value)} — {PII_CHECK_MARK}"


def _laterality(label: str) -> str | None:
    text = label.lower()
    if "right" in text:
        return "right"
    if "left" in text:
        return "left"
    return None


def build_pack(sample_id: str, variant: str, provider: Any) -> dict[str, Any]:
    """Assemble the pack; refuses cases that have an applicable policy."""
    from claimlens.eligibility import check_eligibility
    from claimlens.engine import load_scenarios, replay_reading

    scenarios, inbound = load_scenarios()
    reading = replay_reading(sample_id, variant)
    docs = reading["documents"]
    receipt, cert = docs[0], docs[1]
    if sample_id in inbound:
        service = receipt.get("service_date") or ""
        eligibility = check_eligibility(scenarios[sample_id]["person"], service)
        if eligibility["outcome"] != "not_member_or_unknown":
            raise ValueError(
                f"{sample_id} is {eligibility['outcome']}; the pack is only for "
                "visitors without an applicable policy."
            )
    bill = receipt.get("kr_bill") or {}
    rows = bill.get("charge_rows") or []
    table = translate_labels([r.get("label", "") for r in rows], provider)
    items = [
        {
            "label_ko": r.get("label", ""),
            "label_en": table[r.get("label", "")],
            "amount": sum(int(r.get(f"col_{n}") or 0) for n in (1, 2, 3, 4)),
        }
        for r in rows
    ]
    total = bill.get("cell_8")
    diags = cert.get("diagnoses", [])
    diag = diags[0] if diags else {}
    facts: dict[str, Any] = {}
    side = _laterality(diag.get("label", ""))
    if side:
        facts["laterality"] = side
    codes = (
        convert_diagnosis(diag["code"], receipt.get("service_date"), facts)
        if diag.get("code")
        else None
    )
    verified = all_passed([*check_kr_bill(bill), *check_kr_lines(receipt)])
    return {
        "sample": sample_id,
        "variant": variant,
        "patient": {
            "name": _pii_of(docs, "name"),
            "date_of_birth": _pii_of(docs, "date_of_birth"),
            "passport": _pii_of(docs, "passport"),
            "patient_id": _pii_of(docs, "patient_id"),
        },
        "pii_conflicts": pii_conflicts(docs),
        "visit": {
            "hospital": receipt.get("provider_name", ""),
            "inpatient": receipt.get("inpatient", False),
            "period_from": bill.get("period_from", ""),
            "period_to": bill.get("period_to", ""),
        },
        "diagnosis": {
            "label": diag.get("label", ""),
            "final": diag.get("final"),
        },
        "codes": codes,
        "items": items,
        "total_krw": total,
        "checks_passed": verified,
        "policy_line": POLICY_LINE,
        "calls": [vars(c) for c in provider.calls],
    }


def format_markdown(pack: dict[str, Any]) -> str:
    patient = pack["patient"]
    conflicts = pack.get("pii_conflicts", {})
    visit = pack["visit"]
    codes = pack["codes"] or {}
    cm = codes.get("cm") or {}
    pitfall = codes.get("pitfall")
    stay = "inpatient" if visit["inpatient"] else "outpatient"
    lines = [
        f"# Claim Pack: {pack['sample']}",
        "",
        pack["policy_line"],
        "",
        "## Patient and visit",
        "",
        _pii_line("Name", patient["name"], conflicts.get("name")),
        _pii_line("Date of birth", patient["date_of_birth"], conflicts.get("date_of_birth")),
        _pii_line("Passport", patient["passport"], conflicts.get("passport")),
        _pii_line("Patient ID", patient["patient_id"], conflicts.get("patient_id")),
        f"- Hospital: {visit['hospital']}",
        f"- Stay: {stay}, {visit['period_from']} to {visit['period_to']}",
        "",
        "## Diagnosis codes",
        "",
        f"- Certificate: {pack['diagnosis']['label'] or '-'}",
        f"- KCD: {codes.get('kcd', '-')}",
        f"- WHO ICD-10: {codes.get('who', '-')}"
        + (f" ({codes['attribute']})" if codes.get("attribute") else ""),
        f"- ICD-10-CM candidate: {cm.get('chosen', '-')}",
    ]
    for question in cm.get("questions", []):
        lines.append(f"  - Needed to narrow: {question}")
    if pitfall:
        lines.append(f"- Warning: {pitfall['warning']}")
    lines.append(f"- {codes.get('disclaimer', CODE_DISCLAIMER)}")
    if pack["diagnosis"]["final"] is False:
        lines.append("- Note: the certificate marks a clinical estimate; a final diagnosis may be requested.")
    lines += ["", "## Itemized bill (KRW)", ""]
    for item in pack["items"]:
        lines.append(f"- {item['label_en']} ({item['label_ko']}): {item['amount']:,}")
    total = pack["total_krw"]
    lines.append(f"- Total: {total if total is None else f'{total:,}'}")
    lines.append(f"- Receipt arithmetic verified: {'pass' if pack['checks_passed'] else 'FAIL'}")
    lines.append(f"- {TRANSLATION_NOTE}")
    lines += ["", "## Checklist before leaving", ""]
    lines += [f"- {entry}" for entry in CHECKLIST]
    lines += ["", "## Filing deadlines", "", f"- {GENERIC_DEADLINE}", ""]
    return "\n".join(lines)


def format_html(pack: dict[str, Any]) -> str:
    patient = pack["patient"]
    conflicts = pack.get("pii_conflicts", {})
    visit = pack["visit"]
    codes = pack["codes"] or {}
    cm = codes.get("cm") or {}
    pitfall = codes.get("pitfall")
    stay = "inpatient" if visit["inpatient"] else "outpatient"
    rows = "\n".join(
        f"<tr><td>{html.escape(i['label_en'])}<br/><span lang=\"ko\">"
        f"{html.escape(i['label_ko'])}</span></td>"
        f"<td style=\"text-align:right\">{i['amount']:,}</td></tr>"
        for i in pack["items"]
    )
    questions = "".join(f"<li>Needed to narrow: {html.escape(q)}</li>" for q in cm.get("questions", []))
    warn = f"<p>Warning: {html.escape(pitfall['warning'])}</p>" if pitfall else ""
    final = (
        "<p>Note: the certificate marks a clinical estimate; "
        "a final diagnosis may be requested.</p>"
        if pack["diagnosis"]["final"] is False
        else ""
    )
    checks = "".join(f"<li>{html.escape(entry)}</li>" for entry in CHECKLIST)
    total = pack["total_krw"]
    format_total = "-" if total is None else f"{total:,}"
    attribute = (
        f" ({html.escape(str(codes.get('attribute')))})" if codes.get("attribute") else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/><title>Claim Pack: {html.escape(pack["sample"])}</title></head>
<body>
<p><strong>{html.escape(pack["policy_line"])}</strong></p>
<h2>Patient and visit</h2>
<ul>
<li>{html_pii("Name", patient["name"], conflicts.get("name"))}</li>
<li>{html_pii("Date of birth", patient["date_of_birth"], conflicts.get("date_of_birth"))}</li>
<li>{html_pii("Passport", patient["passport"], conflicts.get("passport"))}</li>
<li>{html_pii("Patient ID", patient["patient_id"], conflicts.get("patient_id"))}</li>
<li>Hospital: {html.escape(visit["hospital"])}</li>
<li>Stay: {stay}, {html.escape(visit["period_from"])} to {html.escape(visit["period_to"])}</li>
</ul>
<h2>Diagnosis codes</h2>
<p>Certificate: {html.escape(pack["diagnosis"]["label"] or "-")}</p>
<ul>
<li>KCD: {html.escape(str(codes.get("kcd", "-")))}</li>
<li>WHO ICD-10: {html.escape(str(codes.get("who", "-")))}{attribute}</li>
<li>ICD-10-CM candidate: {html.escape(str(cm.get("chosen", "-")))}</li>
</ul>
<ul>{questions}</ul>
{warn}
<p>{html.escape(str(codes.get("disclaimer", CODE_DISCLAIMER)))}</p>
{final}
<h2>Itemized bill (KRW)</h2>
<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Item</th><th>Total</th></tr>
{rows}
<tr><td><strong>Total</strong></td><td style="text-align:right"><strong>{format_total}</strong></td></tr>
</table>
<p>Receipt arithmetic verified: {"pass" if pack["checks_passed"] else "FAIL"}</p>
<p>{html.escape(TRANSLATION_NOTE)}</p>
<h2>Checklist before leaving</h2>
<ul>{checks}</ul>
<h2>Filing deadlines</h2>
<ul><li>{html.escape(GENERIC_DEADLINE)}</li></ul>
</body>
</html>
"""
