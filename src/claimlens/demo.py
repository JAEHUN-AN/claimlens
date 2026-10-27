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
from claimlens.engine import load_scenarios, replay_reading
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


def _rel(from_dir: Path, target: Path) -> str:
    start = os.path.normpath(os.path.abspath(from_dir))
    end = os.path.normpath(os.path.abspath(target))
    return os.path.relpath(end, start).replace(os.sep, "/")


def _reading_section(reading: dict[str, Any]) -> dict[str, Any]:
    docs = reading["documents"]
    receipt, cert = docs[0], docs[1]
    bill = receipt.get("kr_bill")
    checks = (
        [{"name": c.name, "passed": c.passed} for c in (*check_kr_bill(bill), *check_kr_lines(receipt))]
        if bill
        else []
    )
    total = receipt.get("total_amount")
    return {
        "docs": [d.get("doc_type", "?") for d in docs],
        "currency": receipt.get("currency", "-"),
        "total": f"{total:,.2f}".rstrip("0").rstrip(".") if total is not None else "-",
        "diags": [d.get("code", "") for d in cert.get("diagnoses", [])],
        "checks": checks,
        "all_passed": all_passed([*check_kr_bill(bill), *check_kr_lines(receipt)]) if bill else None,
    }


def scene_payload(sample_id: str, title: str, dst: Path) -> dict[str, Any]:
    scenarios, inbound = load_scenarios()
    reading = replay_reading(sample_id, "photo")
    receipt = reading["documents"][0]
    payload: dict[str, Any] = {
        "id": sample_id,
        "title": title,
        "reading": _reading_section(reading),
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
        payload["pack"] = {
            "policy_line": pack["policy_line"],
            "patient": pack["patient"],
            "pii_conflicts": pack["pii_conflicts"],
            "pii_mark": PII_CHECK_MARK,
            "visit": pack["visit"],
            "diagnosis": pack["diagnosis"],
            "codes": pack["codes"],
            "items": pack["items"],
            "total_krw": pack["total_krw"],
            "checks_passed": pack["checks_passed"],
            "translation_note": TRANSLATION_NOTE,
            "checklist": CHECKLIST,
            "deadline": GENERIC_DEADLINE,
        }
    else:
        card = build_rationale(sample_id, "photo", ReplayProvider())
        payload["card"] = {
            "decision": card["decision"],
            "amount": f"{card['amount_krw']:,} KRW",
            "summary": card["summary"],
            "steps": card["steps"],
            "clauses": card["clauses"],
            "deductible": card["deductible"],
            "guardrails": card["guardrails"],
        }
    return payload


def _tool_summary(tool: str, result: dict[str, Any]) -> str:
    if result.get("error"):
        return result["error"]
    if tool == "read_documents":
        hidden = [k for k, v in result.get("kr_cells", {}).items() if v == "hidden"]
        docs = ", ".join(result.get("documents", []))
        return f"{docs}; {result.get('currency')} total {result.get('total')}; hidden: {hidden}"
    if tool == "run_checks":
        checks = result.get("checks", [])
        passed = sum(1 for c in checks if c["passed"])
        failing = [c["name"] for c in checks if not c["passed"]]
        text = f"{passed}/{len(checks)} pass"
        return text if not failing else f"{text}; failing: {', '.join(failing)}"
    if tool == "reread_cells":
        return f"corrected: {result.get('corrected', [])}"
    if tool == "decide_eligibility":
        return f"{result.get('outcome')} ({result.get('rule')})"
    if tool == "convert_codes":
        cm = (result.get("cm") or {}).get("chosen", "-")
        return f"WHO {result.get('who')} + {result.get('attribute')}; CM {cm}"
    if tool == "adjudicate":
        return f"{result.get('decision')} {result.get('amount_krw'):,} KRW"
    return json.dumps(result, ensure_ascii=False)[:200]


def agent_scene_payload(dst: Path) -> dict[str, Any]:
    from claimlens.agent import load_trace

    scene_id, title, trace_name, sample_id = AGENT_SCENE
    recorded = load_trace(trace_name)
    entries = []
    for item in recorded["trace"]:
        kind = item["kind"]
        if kind == "question":
            entries.append(
                {
                    "n": item["n"],
                    "kind": kind,
                    "tool": "ask_user",
                    "question": item["question"],
                    "why_needed": item["why_needed"],
                    "answer": item["answer"],
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
                    "summary": _tool_summary(item["tool"], item["result"]),
                }
            )
    tokens = sum(u.get("total_tokens", 0) for u in recorded.get("usages", []))
    payload: dict[str, Any] = {
        "id": scene_id,
        "title": title,
        "reading": None,
        "eligibility": None,
        "card": None,
        "pack": None,
        "timeline": {
            "entries": entries,
            "outcome": recorded.get("outcome", {}),
            "model_calls": len(recorded.get("usages", [])),
            "tokens": tokens,
        },
        "images": [],
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
