"""Assemble the offline demo page from replay caches only.

No API key, no Neo4j: every number comes from a committed recording.
"""

import json
import os
from pathlib import Path
from typing import Any

from claimlens.checks import all_passed, check_kr_bill, check_kr_lines
from claimlens.claimpack import (
    CHECKLIST,
    GENERIC_DEADLINE,
    PII_CHECK_MARK,
    TRANSLATION_NOTE,
    build_pack,
)
from claimlens.demo_template import render_page
from claimlens.eligibility import check_eligibility
from claimlens.engine import copay_rate_from_bill, load_scenarios, replay_reading
from claimlens.provenance import ProvBuilder
from claimlens.providers.replay import ReplayProvider
from claimlens.rationale import build_rationale
from claimlens.reader import resolve_sample_images

SCENES = [
    ("A_niseko_wrist", "Scene A — Korean traveller treated in Japan"),
    ("S2_seoul_worker_bronchitis", "Scene S2 — insured worker treated in Seoul"),
    ("S3_us_tourist_hip_fracture", "Scene S3 — uninsured visitor treated in Seoul"),
]

MASKED_AFTER = {
    "S2_seoul_worker_bronchitis": ("receipt", "S2_receipt_after.png"),
    "S3_us_tourist_hip_fracture": ("medical_certificate", "S3_cert_after.png"),
}

AGENT_SCENE = (
    "agent_s2_hidden_copay",
    "Scene Agent — S2 with hidden copay cells",
    "s2_hidden_copay",
    "S2_seoul_worker_bronchitis",
)

VOICE_SCENE = (
    "voice_factory_fall",
    "Scene Voice — factory fall (spoken intake)",
    (("en", "W_factory_fall_en"), ("ko", "W_factory_fall_ko")),
)

DOC_CAPTION = {"receipt": "Receipt", "medical_certificate": "Certificate"}

TERM_LABELS = (
    "flat amount by institution",
    "proportional share of claimed",
    "claimed times copay rate",
)


def _rel(from_dir: Path, target: Path) -> str:
    start = os.path.normpath(os.path.abspath(from_dir))
    end = os.path.normpath(os.path.abspath(target))
    return os.path.relpath(end, start).replace(os.sep, "/")


def _fmt_total(total: float | None) -> str:
    return f"{total:,.2f}".rstrip("0").rstrip(".") if total is not None else "-"


def _reading_section(
    reading: dict[str, Any], prov: ProvBuilder, prefix: str
) -> dict[str, Any]:
    docs = reading["documents"]
    receipt, cert = docs[0], docs[1]
    bill = receipt.get("kr_bill")
    checks = (
        [{"name": c.name, "passed": c.passed} for c in (*check_kr_bill(bill), *check_kr_lines(receipt))]
        if bill
        else []
    )
    total = receipt.get("total_amount")
    if total is None:
        total_ref: Any = "-"
    else:
        pid = prov.add(
            f"{prefix}-total",
            "reading",
            "Receipt total",
            _fmt_total(total),
            f"receipt total_amount {total}",
        )
        total_ref = prov.num(pid, _fmt_total(total))
    diags = []
    for n, diag in enumerate(cert.get("diagnoses", [])):
        code = diag.get("code", "")
        pid = prov.add(
            f"{prefix}-diag-{n}",
            "reading",
            "Certificate diagnosis code",
            code,
            f"certificate diagnoses[{n}].code {code}",
        )
        diags.append(prov.num(pid, code))
    return {
        "docs": [d.get("doc_type", "?") for d in docs],
        "currency": receipt.get("currency", "-"),
        "total": total_ref,
        "diags": diags,
        "checks": checks,
        "all_passed": all_passed([*check_kr_bill(bill), *check_kr_lines(receipt)]) if bill else None,
    }


def _deductible_section(
    check: dict[str, Any], bill: dict[str, Any], prov: ProvBuilder, prefix: str
) -> dict[str, Any]:
    terms = []
    for n, (value, label) in enumerate(zip(check["terms"], TERM_LABELS)):
        pid = prov.add(
            f"{prefix}-ded{n}",
            "check",
            f"Deductible term {n + 1} ({label})",
            f"{value:,}",
            f"deductible term {n + 1} = {value:,}",
        )
        terms.append(prov.num(pid, f"{value:,}"))
    head = f"max({', '.join(f'{t:,}' for t in check['terms'])})"
    ours_pid = prov.add(
        f"{prefix}-ded-ours",
        "check",
        "ClaimLens deductible",
        f"{check['ours']:,}",
        head,
        formula=f"{head} = {check['ours']:,}",
        operands=[t["prov"] for t in terms],
    )
    engine_pid = prov.add(
        f"{prefix}-ded-engine",
        "clausegraph",
        "Engine payable amount",
        f"{check['engine']:,}",
        f"engine output amount {check['engine']}",
    )
    cells: dict[str, Any] = {}
    c1, c2 = (bill or {}).get("cell_1"), (bill or {}).get("cell_2")
    for key, raw in (("c1", c1), ("c2", c2)):
        if isinstance(raw, int):
            pid = prov.add(
                f"{prefix}-{key}",
                "reading",
                f"Receipt cell {key[1]}",
                f"{raw:,}",
                f"receipt cell_{key[1]} {raw}",
            )
            cells[key] = prov.num(pid, f"{raw:,}")
        else:
            cells[key] = {"v": "-"}
    rate = copay_rate_from_bill(bill)
    if rate is None:
        cells["copay"] = {"v": "-"}
    else:
        pid = prov.add(
            f"{prefix}-copay",
            "check",
            "Copay rate",
            str(rate),
            "copay rate from cells 1 and 2",
            formula="① ÷ (① + ②)",
            operands=[cells["c1"].get("prov", ""), cells["c2"].get("prov", "")],
        )
        cells["copay"] = prov.num(pid, str(rate))
    return {
        "terms": terms,
        "ours": prov.num(ours_pid, f"{check['ours']:,}"),
        "engine": prov.num(engine_pid, f"{check['engine']:,}"),
        "match": check["match"],
        "cells": cells,
    }


def _pack_section(
    pack: dict[str, Any], rows: list[dict[str, Any]], prov: ProvBuilder, prefix: str
) -> dict[str, Any]:
    by_label = {r.get("label", ""): r for r in rows}
    items = []
    for n, item in enumerate(pack["items"]):
        row = by_label.get(item["label_ko"], {})
        cols = [int(row.get(f"col_{k}") or 0) for k in (1, 2, 3, 4)]
        pid = prov.add(
            f"{prefix}-line-{n}",
            "check",
            f"Bill line total ({item['label_ko']})",
            f"{item['amount']:,}",
            f"row '{item['label_ko']}' columns sum",
            formula=" + ".join(f"{c:,}" for c in cols),
        )
        items.append(
            {
                "label_ko": item["label_ko"],
                "label_en": item["label_en"],
                "amount": prov.num(pid, f"{item['amount']:,}"),
            }
        )
    total = pack["total_krw"]
    total_pid = prov.add(
        f"{prefix}-pack-total",
        "reading",
        "Bill total",
        f"{total:,}" if total is not None else "-",
        f"receipt cell_8 {total}",
    )
    codes = pack["codes"] or {}
    cm = codes.get("cm") or {}
    kcd_pid = prov.add(
        f"{prefix}-kcd", "reading", "KCD code", codes.get("kcd", "-"), "certificate code"
    )
    who_pid = prov.add(
        f"{prefix}-who",
        "rule",
        "WHO ICD-10 code",
        codes.get("who", "-"),
        "KCD-9 truncation to 4 characters",
    )
    cm_pid = prov.add(
        f"{prefix}-cm",
        "rule",
        "ICD-10-CM candidate",
        cm.get("chosen", "-"),
        "FY2027 defaults plus narrowing facts",
    )
    return {
        "policy_line": pack["policy_line"],
        "patient": pack["patient"],
        "pii_conflicts": pack["pii_conflicts"],
        "pii_mark": PII_CHECK_MARK,
        "visit": pack["visit"],
        "diagnosis": pack["diagnosis"],
        "codes": {
            "kcd": prov.num(kcd_pid, codes.get("kcd", "-")),
            "who": prov.num(who_pid, codes.get("who", "-")),
            "attribute": codes.get("attribute"),
            "cm": {"chosen": prov.num(cm_pid, cm.get("chosen", "-"))},
            "questions": cm.get("questions", []),
            "pitfall": codes.get("pitfall"),
            "disclaimer": codes.get("disclaimer", ""),
        },
        "items": items,
        "total_krw": prov.num(total_pid, f"{total:,}" if total is not None else "-"),
        "checks_passed": pack["checks_passed"],
        "translation_note": TRANSLATION_NOTE,
        "checklist": CHECKLIST,
        "deadline": GENERIC_DEADLINE,
    }


def scene_payload(sample_id: str, title: str, dst: Path) -> dict[str, Any]:
    scenarios, inbound = load_scenarios()
    reading = replay_reading(sample_id, "photo")
    receipt = reading["documents"][0]
    prov = ProvBuilder()
    prefix = sample_id.split("_")[0].lower()
    payload: dict[str, Any] = {
        "id": sample_id,
        "title": title,
        "reading": _reading_section(reading, prov, prefix),
        "eligibility": None,
        "card": None,
        "pack": None,
        "images": [],
    }
    if sample_id in inbound:
        service = receipt.get("service_date") or ""
        payload["eligibility"] = check_eligibility(scenarios[sample_id]["person"], service)
    base = Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples")) / sample_id
    masked_doc, masked_name = MASKED_AFTER.get(sample_id, (None, None))
    masked_path = Path("docs/masking") / masked_name if masked_name else None
    for stem, img in zip(("receipt", "medical_certificate"), resolve_sample_images(base, "photo")):
        caption = f"{DOC_CAPTION[stem]} (photo)"
        src = _rel(dst.parent, img)
        if stem == masked_doc and masked_path is not None and masked_path.exists():
            src = _rel(dst.parent, masked_path)
            caption = f"{DOC_CAPTION[stem]} (masked copy)"
        payload["images"].append({"src": src, "caption": caption})
    if sample_id == "S3_us_tourist_hip_fracture":
        pack = build_pack(sample_id, "photo", ReplayProvider())
        rows = (receipt.get("kr_bill") or {}).get("charge_rows") or []
        payload["pack"] = _pack_section(pack, rows, prov, prefix)
    else:
        card = build_rationale(sample_id, "photo", ReplayProvider())
        bill = receipt.get("kr_bill")
        deductible = (
            _deductible_section(card["deductible"], bill or {}, prov, prefix)
            if card["deductible"]
            else None
        )
        operands: list[str] = []
        if deductible:
            operands = (
                [t["prov"] for t in deductible["terms"]]
                + [deductible["ours"]["prov"]]
                + [deductible["cells"][k].get("prov", "") for k in ("c1", "c2", "copay")]
            )
            operands = [o for o in operands if o]
        amount_pid = prov.add(
            f"{prefix}-amount",
            "clausegraph",
            "Payable amount",
            f"{card['amount_krw']:,}",
            f"engine output amount {card['amount_krw']}",
            operands=operands,
        )
        payload["card"] = {
            "decision": card["decision"],
            "amount": prov.num(amount_pid, f"{card['amount_krw']:,} KRW"),
            "summary": card["summary"],
            "steps": card["steps"],
            "clauses": card["clauses"],
            "deductible": deductible,
            "guardrails": card["guardrails"],
        }
    payload["provenance"] = prov.records
    return payload


def _tool_segments(
    tool: str, result: dict[str, Any], prov: ProvBuilder, prefix: str, step: int
) -> list[dict[str, str]]:
    """Timeline line as text/number segments; every number gets provenance."""
    if result.get("error"):
        return [{"t": result["error"], "noprov": "1"}]
    if tool == "read_documents":
        hidden = [k for k, v in result.get("kr_cells", {}).items() if v == "hidden"]
        docs = ", ".join(result.get("documents", []))
        total = result.get("total")
        pid = prov.add(
            f"{prefix}-t{step}-total",
            "reading",
            "Receipt total",
            str(total),
            f"receipt total_amount {total}",
        )
        return [
            {"t": f"{docs}; {result.get('currency')} total "},
            {"n": str(total), "prov": pid},
            {"t": f"; hidden: {hidden}"},
        ]
    if tool == "run_checks":
        checks = result.get("checks", [])
        passed = sum(1 for c in checks if c["passed"])
        pid = prov.add(
            f"{prefix}-t{step}-checks",
            "check",
            "Receipt checks passed",
            f"{passed}/{len(checks)}",
            f"{passed} of {len(checks)} receipt checks passed",
        )
        failing = [c["name"] for c in checks if not c["passed"]]
        tail = "" if not failing else f"; failing: {', '.join(failing)}"
        return [{"n": f"{passed}/{len(checks)}", "prov": pid}, {"t": f" pass{tail}"}]
    if tool == "reread_cells":
        return [{"t": f"corrected: {result.get('corrected', [])}"}]
    if tool == "decide_eligibility":
        return [{"t": f"{result.get('outcome')} ({result.get('rule')})"}]
    if tool == "convert_codes":
        segs: list[dict[str, str]] = [{"t": "WHO "}]
        pid = prov.add(
            f"{prefix}-t{step}-who",
            "rule",
            "WHO ICD-10 code",
            str(result.get("who")),
            "KCD-9 truncation to 4 characters",
        )
        segs.append({"n": str(result.get("who")), "prov": pid})
        if result.get("attribute"):
            segs.append({"t": f" + {result['attribute']}"})
        chosen = (result.get("cm") or {}).get("chosen")
        if chosen:
            pid = prov.add(
                f"{prefix}-t{step}-cm",
                "rule",
                "ICD-10-CM candidate",
                str(chosen),
                "FY2027 defaults plus narrowing facts",
            )
            segs += [{"t": "; CM "}, {"n": str(chosen), "prov": pid}]
        return segs
    if tool == "adjudicate":
        pid = prov.add(
            f"{prefix}-t{step}-amount",
            "clausegraph",
            "Payable amount",
            f"{result['amount_krw']:,}",
            f"engine output amount {result['amount_krw']}",
        )
        return [
            {"t": f"{result.get('decision')} "},
            {"n": f"{result['amount_krw']:,}", "prov": pid},
            {"t": " KRW"},
        ]
    return [{"t": json.dumps(result, ensure_ascii=False)[:200], "noprov": "1"}]


def agent_scene_payload(dst: Path) -> dict[str, Any]:
    from claimlens.agent import load_trace

    scene_id, title, trace_name, sample_id = AGENT_SCENE
    recorded = load_trace(trace_name)
    prov = ProvBuilder()
    prefix = "agent"
    entries = []
    for item in recorded["trace"]:
        kind = item["kind"]
        if kind == "question":
            pid = prov.add(
                f"{prefix}-t{item['n']}-answer",
                "user",
                "User answer",
                item["answer"],
                f"user answer: {item['answer']}",
            )
            entries.append(
                {
                    "n": item["n"],
                    "kind": kind,
                    "tool": "ask_user",
                    "question": item["question"],
                    "why_needed": item["why_needed"],
                    "answer": prov.num(pid, item["answer"]),
                }
            )
        elif kind == "final":
            entries.append({"n": item["n"], "kind": kind, "text": item["text"]})
        elif kind == "stopped":
            entries.append({"n": item["n"], "kind": kind, "text": item["reason"]})
        else:
            entries.append(
                {
                    "n": item["n"],
                    "kind": kind,
                    "tool": item["tool"],
                    "segments": _tool_segments(
                        item["tool"], item["result"], prov, prefix, item["n"]
                    ),
                }
            )
    tokens = sum(u.get("total_tokens", 0) for u in recorded.get("usages", []))
    turns_pid = prov.add(
        f"{prefix}-turns",
        "check",
        "Model turns",
        str(len(recorded.get("usages", []))),
        f"{len(recorded.get('usages', []))} recorded model turns",
    )
    tokens_pid = prov.add(
        f"{prefix}-tokens",
        "check",
        "Total tokens",
        f"{tokens:,}",
        f"token sum across turns: {tokens:,}",
    )
    outcome = dict(recorded.get("outcome", {}))
    if outcome.get("decision"):
        amount_pid = prov.add(
            f"{prefix}-amount",
            "clausegraph",
            "Payable amount",
            f"{outcome['amount_krw']:,}",
            f"engine output amount {outcome['amount_krw']}",
        )
        outcome["amount"] = prov.num(amount_pid, f"{outcome['amount_krw']:,} KRW")
    payload: dict[str, Any] = {
        "id": scene_id,
        "title": title,
        "reading": None,
        "eligibility": None,
        "card": None,
        "pack": None,
        "timeline": {
            "entries": entries,
            "outcome": outcome,
            "model_calls": prov.num(turns_pid, str(len(recorded.get("usages", [])))),
            "tokens": prov.num(tokens_pid, f"{tokens:,}"),
        },
        "images": [],
        "provenance": prov.records,
    }
    base = Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples")) / sample_id
    for stem, img in zip(("receipt", "medical_certificate"), resolve_sample_images(base, "photo")):
        payload["images"].append(
            {"src": _rel(dst.parent, img), "caption": f"{DOC_CAPTION[stem]} (photo)"}
        )
    return payload


def voice_scene_payload(dst: Path) -> dict[str, Any]:
    from claimlens.providers.replay import ReplayProvider
    from claimlens.voice import intake

    scene_id, title, clips = VOICE_SCENE
    provider = ReplayProvider()
    audio_dir = Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples")) / "audio"
    rendered = []
    for lang, clip in clips:
        result = intake(clip, live=False, provider=provider)
        rendered.append(
            {
                "lang": lang,
                "audio": _rel(dst.parent, audio_dir / f"{clip}.wav"),
                "transcript": result["transcript"],
                "facts": result["facts"],
                "quotes": result["quotes"],
                "to_confirm": sorted(result["to_confirm"]),
                "confirmations": result["confirmations"],
            }
        )
    first = intake(clips[0][1], live=False, provider=provider)
    return {
        "id": scene_id,
        "title": title,
        "reading": None,
        "eligibility": first["eligibility"],
        "card": None,
        "pack": None,
        "timeline": None,
        "clips": rendered,
        "next_step": first["next_step"],
    }


def export_demo(dst: Path | str = "docs/demo.html") -> Path:
    dst = Path(dst)
    scenes = [scene_payload(sample_id, title, dst) for sample_id, title in SCENES]
    scenes.append(agent_scene_payload(dst))
    scenes.append(voice_scene_payload(dst))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(render_page({"scenes": scenes}), encoding="utf-8")
    return dst
