"""Assemble the offline demo page from replay caches only.

No API key, no Neo4j: every number comes from a committed recording.
"""

import os
from pathlib import Path
from typing import Any

from claimlens.checks import all_passed, check_kr_bill, check_kr_lines
from claimlens.claimpack import build_pack, format_html
from claimlens.demo_template import render_page
from claimlens.eligibility import check_eligibility
from claimlens.engine import load_scenarios, replay_reading
from claimlens.providers.replay import ReplayProvider
from claimlens.rationale import build_rationale, format_card
from claimlens.reader import resolve_sample_images

SCENES = [
    ("A_niseko_wrist", "Scene A — Korean traveller treated in Japan"),
    ("S2_seoul_worker_bronchitis", "Scene S2 — insured worker treated in Seoul"),
    ("S3_us_tourist_hip_fracture", "Scene S3 — uninsured visitor treated in Seoul"),
]

MASKED_AFTER = {
    "S2_seoul_worker_bronchitis": "S2_receipt_after.png",
    "S3_us_tourist_hip_fracture": "S3_cert_after.png",
}


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
    for img in resolve_sample_images(base, "photo"):
        payload["images"].append(_rel(dst.parent, img))
    after = MASKED_AFTER.get(sample_id)
    if after:
        masked = Path("docs/masking") / after
        if masked.exists():
            payload["images"].append(_rel(dst.parent, masked))
    if sample_id == "S3_us_tourist_hip_fracture":
        pack = build_pack(sample_id, "photo", ReplayProvider())
        payload["pack"] = {"html": format_html(pack)}
    else:
        card = build_rationale(sample_id, "photo", ReplayProvider())
        payload["card"] = {
            "decision": card["decision"],
            "amount": f"{card['amount_krw']:,} KRW",
            "summary": card["summary"],
            "markdown": format_card(card),
        }
    return payload


def export_demo(dst: Path | str = "docs/demo.html") -> Path:
    dst = Path(dst)
    scenes = [scene_payload(sample_id, title, dst) for sample_id, title in SCENES]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(render_page({"scenes": scenes}), encoding="utf-8")
    return dst
