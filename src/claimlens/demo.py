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
from claimlens.supervision import build_walkthrough, replay_trace_guards

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

MISMATCH_SCENE = (
    "mismatch_s2r_s3c",
    "Scene Mismatch — S2 receipt, S3 certificate",
    "S2r-S3c",
)

DOC_CAPTION = {"receipt": "Receipt", "medical_certificate": "Certificate"}

SCENE_TITLES = {
    "A_niseko_wrist": {
        "en": "Scene A — Korean traveller treated in Japan",
        "ko": "장면 A — 일본에서 치료받은 한국 여행자",
    },
    "S2_seoul_worker_bronchitis": {
        "en": "Scene S2 — insured worker treated in Seoul",
        "ko": "장면 S2 — 서울에서 치료받은 가입 근로자",
    },
    "S3_us_tourist_hip_fracture": {
        "en": "Scene S3 — uninsured visitor treated in Seoul",
        "ko": "장면 S3 — 서울에서 치료받은 미가입 방문자",
    },
    "agent_s2_hidden_copay": {
        "en": "Scene Agent — S2 with hidden copay cells",
        "ko": "장면 Agent — 본인부담 칸이 숨겨진 S2",
    },
    "voice_factory_fall": {
        "en": "Scene Voice — factory fall (spoken intake)",
        "ko": "장면 Voice — 공장 추락 (음성 접수)",
    },
}

# Kept beside the table: the mismatch scene pairs two samples, not one.
SCENE_TITLES["mismatch_s2r_s3c"] = {
    "en": "Scene Mismatch — S2 receipt, S3 certificate",
    "ko": "장면 Mismatch — S2 영수증과 S3 진단서",
}

FLOW_LABELS = {
    "read_documents": "Reading",
    "run_checks": "Checks",
    "reread_cells": "Re-read",
    "decide_eligibility": "Eligibility",
    "convert_codes": "Codes",
    "adjudicate": "Decision",
    "build_claim_pack": "Claim Pack",
    "ask_user": "Question",
}

TERM_LABELS = (
    "flat amount by institution",
    "proportional share of claimed",
    "claimed times copay rate",
)


def _rel(from_dir: Path, target: Path) -> str:
    start = _normpath(os.path.abspath(from_dir))
    end = _normpath(os.path.abspath(target))
    return os.path.relpath(end, start).replace(os.sep, "/")


def _normpath(path: str) -> str:
    # Strip the extended-length prefix; it names the same location.
    return os.path.normpath(path).removeprefix("\\\\?\\")


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


def _recovery_section(
    sample_id: str,
    scenarios: dict[str, Any],
    prov: ProvBuilder,
    prefix: str,
    dst: Path,
) -> dict[str, Any]:
    """Fail-to-recovery story: clean base reading plus one narrow re-read."""
    from claimlens.eval import compare, ground_truth
    from claimlens.verify import verify_receipt

    truth = ground_truth(scenarios[sample_id])
    reading = replay_reading(sample_id, "clean")
    receipt = reading["documents"][0]
    base = Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples")) / sample_id
    image = resolve_sample_images(base, "clean")[0]
    result = verify_receipt(receipt, image, ReplayProvider())
    merged = {"documents": [result["receipt"], reading["documents"][1]]}
    before = compare(sample_id, truth, reading)
    after = compare(sample_id, truth, merged)

    def _num(pid: str, label: str, value: str, source: str) -> dict[str, str]:
        return prov.num(
            prov.add(f"{prefix}-rec-{pid}", "check", label, value, source), value
        )

    def _side(
        metrics: dict[str, Any], tag: str, noun: str, origin: str
    ) -> dict[str, Any]:
        return {
            "lines": _num(
                f"lines-{tag}",
                f"{noun} lines",
                metrics["lines"],
                f"{origin} lines {metrics['lines']}",
            ),
            "amounts": metrics["amounts"],
            "checks": metrics["checks"],
            "kr_cells": _num(
                f"cells-{tag}",
                f"{noun} KR cells",
                metrics["kr_cells"],
                f"{origin} kr cells {metrics['kr_cells']}",
            ),
        }

    return {
        "before": _side(before, "before", "Base reading", "clean base reading"),
        "failed_before": result.get("failed_before", []),
        "corrected": result.get("corrected", []),
        "after": _side(after, "after", "Re-read", "narrow re-read"),
        "status": result["status"],
        "image": {"src": _rel(dst.parent, image), "caption": "Receipt (clean)"},
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
        "titles": SCENE_TITLES[sample_id],
        "reading": _reading_section(reading, prov, prefix),
        "eligibility": None,
        "card": None,
        "pack": None,
        "recovery": None,
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
    flow_tokens: dict[str, int | None] = {"reading": None, "card": None, "pack": None}
    flow_tokens["reading"] = _reading_tokens(sample_id, "photo")
    if sample_id == "S3_us_tourist_hip_fracture":
        pack_provider = ReplayProvider()
        pack = build_pack(sample_id, "photo", pack_provider)
        flow_tokens["pack"] = sum(c.total_tokens for c in pack_provider.calls)
        rows = (receipt.get("kr_bill") or {}).get("charge_rows") or []
        payload["pack"] = _pack_section(pack, rows, prov, prefix)
        payload["recovery"] = _recovery_section(
            sample_id, scenarios, prov, prefix, dst
        )
    else:
        card_provider = ReplayProvider()
        card = build_rationale(sample_id, "photo", card_provider)
        flow_tokens["card"] = sum(c.total_tokens for c in card_provider.calls)
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
    payload["flow_tokens"] = flow_tokens
    return payload


def _reading_tokens(sample_id: str, variant: str) -> int | None:
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.reader import reading_schema

    base = Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples")) / sample_id
    provider = ReplayProvider()
    provider.read_documents(
        resolve_sample_images(base, variant), READING_INSTRUCTIONS, reading_schema()
    )
    return provider.calls[0].total_tokens if provider.calls else None


def _tokens_meta(tokens: int | None) -> str:
    return f"{tokens:,} tokens (recorded)" if tokens else "recorded"


def _scene_flow(sample_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    reading = payload["reading"]
    total = reading["total"]
    total_v = total["v"] if isinstance(total, dict) else total
    tokens = payload.get("flow_tokens") or {}
    steps = [
        {
            "key": "reading",
            "label": "Reading",
            "detail": f"{' + '.join(reading['docs'])} · {reading['currency']} total {total_v}",
            "meta": _tokens_meta(tokens.get("reading")),
        }
    ]
    checks = reading.get("checks", [])
    if checks:
        passed = sum(1 for c in checks if c["passed"])
        steps.append(
            {
                "key": "checks",
                "label": "Checks",
                "detail": f"{passed}/{len(checks)} pass",
                "meta": "deterministic",
            }
        )
    elig = payload.get("eligibility")
    steps.append(
        {
            "key": "eligibility",
            "label": "Eligibility",
            "detail": elig["outcome"] if elig else "Korean traveller abroad — engine path",
            "meta": "deterministic",
        }
    )
    if payload.get("card"):
        card = payload["card"]
        amount_v = card["amount"]["v"] if isinstance(card["amount"], dict) else card["amount"]
        steps.append(
            {
                "key": "decision",
                "label": "Decision",
                "detail": f"{card['decision']} {amount_v}",
                "meta": _tokens_meta(tokens.get("card")),
            }
        )
        result = {
            "badge": card["decision"],
            "title": amount_v,
            "scene": sample_id,
            "engine": True,
        }
    else:
        pack = payload["pack"]
        total_v = pack["total_krw"]["v"]
        steps.append(
            {
                "key": "pack",
                "label": "Claim Pack",
                "detail": f"{len(pack['items'])} lines · total {total_v} KRW",
                "meta": _tokens_meta(tokens.get("pack")),
            }
        )
        result = {
            "badge": "not adjudicated",
            "title": f"Claim Pack · {total_v} KRW",
            "scene": sample_id,
            "engine": False,
        }
    return {
        "id": sample_id,
        "title": payload["title"],
        "titles": payload["titles"],
        "thumb": payload["images"][0]["src"] if payload.get("images") else None,
        "steps": steps,
        "result": result,
    }


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
        trace_tools = {item.get("tool") for item in recorded.get("trace", [])}
        outcome["engine"] = "adjudicate" in trace_tools
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
        "titles": SCENE_TITLES[scene_id],
        "reading": None,
        "eligibility": None,
        "card": None,
        "pack": None,
        "timeline": {
            "entries": entries,
            "outcome": outcome,
            "model_calls": prov.num(turns_pid, str(len(recorded.get("usages", [])))),
            "tokens": prov.num(tokens_pid, f"{tokens:,}"),
            "verification": {
                "trace_guards": replay_trace_guards(AGENT_SCENE[2], hidden_cells={"cell_1", "cell_2"}),
                "walkthrough": build_walkthrough(),
            },
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


def _agent_flow(payload: dict[str, Any]) -> dict[str, Any]:
    from claimlens.agent import load_trace

    recorded = load_trace(AGENT_SCENE[2])
    usages = recorded.get("usages", []) or []
    steps = []
    trace = recorded.get("trace", [])
    for n, item in enumerate(trace):
        kind = item["kind"]
        use = usages[n] if n < len(usages) else {}
        meta = _tokens_meta(use.get("total_tokens"))
        if kind == "question":
            steps.append(
                {
                    "key": "ask_user",
                    "label": "Question",
                    "detail": item["question"][:90],
                    "meta": f"{meta} · user answers",
                }
            )
        elif kind in ("final", "stopped"):
            continue
        else:
            tool = item["tool"]
            segs = _tool_segments(tool, item["result"], ProvBuilder(), "flow", n)
            detail = "".join(s.get("n", s.get("t", "")) for s in segs)[:100]
            steps.append(
                {"key": tool, "label": FLOW_LABELS.get(tool, tool), "detail": detail, "meta": meta}
            )
    outcome = recorded.get("outcome", {})
    used_tools = {item.get("tool") for item in trace}
    return {
        "id": payload["id"],
        "title": payload["title"],
        "titles": payload["titles"],
        "thumb": payload["images"][0]["src"] if payload.get("images") else None,
        "steps": steps,
        "result": {
            "badge": outcome.get("decision", "?"),
            "title": f"{outcome.get('amount_krw', 0):,} KRW",
            "scene": payload["id"],
            "engine": "adjudicate" in used_tools,
        },
    }


def voice_scene_payload(dst: Path) -> dict[str, Any]:
    from claimlens.providers.replay import ReplayProvider
    from claimlens.voice import intake

    scene_id, title, clips = VOICE_SCENE
    provider = ReplayProvider()
    audio_dir = Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples")) / "audio"
    rendered = []
    for lang, clip in clips:
        result = intake(clip, live=False, provider=provider, lang=lang)
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
    first = intake(clips[0][1], live=False, provider=provider, lang=clips[0][0])
    return {
        "id": scene_id,
        "title": title,
        "titles": SCENE_TITLES[scene_id],
        "reading": None,
        "eligibility": first["eligibility"],
        "card": None,
        "pack": None,
        "timeline": None,
        "clips": rendered,
        "next_step": first["next_step"],
    }


def _voice_flow(payload: dict[str, Any]) -> dict[str, Any]:
    from claimlens.providers.replay import ReplayProvider
    from claimlens.voice import intake

    provider = ReplayProvider()
    steps = []
    for lang, clip in VOICE_SCENE[2]:
        result = intake(clip, live=False, provider=provider, lang=lang)
        seconds = (result.get("audio_duration_ms") or 0) / 1000
        steps.append(
            {
                "key": "transcribe",
                "label": f"Transcription ({lang})",
                "detail": f"clip {seconds:.1f} s · {len(result['transcript'].split())} words",
                "meta": "Muse Voice Transcribe (recorded)",
            }
        )
    tokens = sum(c.total_tokens for c in provider.calls)
    steps.append(
        {
            "key": "facts",
            "label": "Fact extraction",
            "detail": "6 facts + quoted words, both clips",
            "meta": _tokens_meta(tokens),
        }
    )
    steps.append(
        {
            "key": "eligibility",
            "label": "Eligibility",
            "detail": f"{payload['eligibility']['outcome']} ({payload['eligibility']['rule']})",
            "meta": "deterministic",
        }
    )
    return {
        "id": payload["id"],
        "title": payload["title"],
        "titles": payload["titles"],
        "thumb": None,
        "steps": steps,
        "result": {
            "badge": payload["eligibility"]["outcome"],
            "title": payload["next_step"],
            "scene": payload["id"],
            "engine": False,
        },
    }


def _eval_section() -> dict[str, Any]:
    from claimlens.eval import eval_all

    rows = []
    matched: list[str] = []
    differed: list[str] = []
    for row in eval_all():
        if row.get("variant") != "photo" or "error" in row:
            continue
        letter = row["sample"].split("_")[0]
        checks = " ".join(
            part for part in (row["kr_cells"], row["checks"]) if part != "n/a"
        ) or "n/a"
        opened = row.get("open") or {}
        rows.append(
            {
                "sample": letter,
                "total": row["total"],
                "lines": row["lines"],
                "diags": row["diags"],
                "checks": checks,
                "pii": row["pii"],
                "open_total": opened.get("total", "-"),
                "open_lines": opened.get("lines", "-"),
                "open_checks": opened.get("checks", "-"),
            }
        )
        if not opened:
            differed.append(f"{letter} no open reading")
            continue
        aspects = [
            aspect
            for aspect, hosted, open_v in (
                ("total", row["total"], opened.get("total")),
                ("lines", row["lines"], opened.get("lines")),
                ("checks", row["checks"], opened.get("checks")),
            )
            if hosted != open_v
        ]
        if aspects:
            differed.extend(f"{letter} {aspect}" for aspect in aspects)
        else:
            matched.append(letter)
    match_part = "/".join(matched) or "none"
    differ_part = ", ".join(differed) or "none"
    line = f"Open weights match hosted on {match_part}; differ on {differ_part}."
    return {"rows": rows, "open_line": line}


def mismatch_scene_payload(dst: Path) -> dict[str, Any]:
    from claimlens.consistency import check_consistency

    scene_id, title, bundle = MISMATCH_SCENE
    provider = ReplayProvider()
    result = check_consistency(bundle, provider)
    cross = check_consistency("Ar-Cc", provider)
    cross = check_consistency("Ar-Cc", provider)
    base = Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples"))
    receipt_img = resolve_sample_images(base / "S2_seoul_worker_bronchitis", "photo")[0]
    masked = Path("docs/masking") / "S3_cert_after.png"
    photo_cert = resolve_sample_images(base / "S3_us_tourist_hip_fracture", "photo")[1]
    cert_src = _rel(dst.parent, masked if masked.exists() else photo_cert)
    images = [
        {"src": _rel(dst.parent, receipt_img), "caption": "Receipt (photo)"},
        {"src": cert_src, "caption": "Certificate (masked copy)"},
    ]
    keys = ("kind", "severity", "layer", "quote_receipt", "quote_cert",
            "reason", "question", "why_needed")
    return {
        "id": scene_id,
        "title": title,
        "titles": SCENE_TITLES[scene_id],
        "reading": None,
        "eligibility": None,
        "card": None,
        "pack": None,
        "timeline": None,
        "clips": None,
        "images": images,
        "mismatch": {
            "bundle": bundle,
            "receipt_sample": "S2_seoul_worker_bronchitis",
            "cert_sample": "S3_us_tourist_hip_fracture",
            "stopped": result["stopped"],
            "claims_check": {
                "label": "A receipt + C certificate",
                "dropped": cross["dropped_quotes"] + cross["unverified_dropped"],
            },
            "dropped_quotes": result["dropped_quotes"],
            "findings": [{k: f.get(k) for k in keys} for f in result["findings"]],
        },
    }


def export_demo(dst: Path | str = "docs/demo.html") -> Path:
    dst = Path(dst)
    scenes = [scene_payload(sample_id, title, dst) for sample_id, title in SCENES]
    scenes.append(agent_scene_payload(dst))
    scenes.append(voice_scene_payload(dst))
    scenes.append(mismatch_scene_payload(dst))
    flow = {
        "examples": [
            _scene_flow(scenes[0]["id"], scenes[0]),
            _scene_flow(scenes[1]["id"], scenes[1]),
            _scene_flow(scenes[2]["id"], scenes[2]),
            _agent_flow(scenes[3]),
            _voice_flow(scenes[4]),
        ],
        "eval": _eval_section(),
    }
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(render_page({"scenes": scenes, "flow": flow}), encoding="utf-8")
    return dst
