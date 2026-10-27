"""Rationale tests: pure tracing checks plus replay-pinned English cards."""

import json
from pathlib import Path

import pytest

from claimlens.rationale import (
    build_rationale,
    check_rationale,
    draft_numbers,
    engine_numbers,
    rationale_payload,
)

CACHE = Path(__file__).resolve().parents[1] / "cache" / "engine"

PAYLOAD = {
    "decision": "PAID",
    "amount_krw": 1000,
    "claimed_krw": 1000,
    "reason": "paid in full",
    "steps": [{"step": "step-one", "summary": "did 2 things", "detail": {}}],
    "evidence": [{"id": "v1/prod/article-1", "title": "t", "quote": "q", "role": "coverage"}],
    "guardrails": [],
}


def test_check_accepts_traced_numbers():
    draft = {
        "summary": "Paid 1,000 in full.",
        "steps": [{"step": "step-one", "text": "Did two things."}],
        "clauses": [{"id": "v1/prod/article-1", "text": "The clause covers it."}],
    }
    check_rationale(draft, PAYLOAD)


def test_check_rejects_invented_number():
    draft = {
        "summary": "Paid 9,999 in full.",
        "steps": [{"step": "step-one", "text": "Done."}],
        "clauses": [],
    }
    with pytest.raises(ValueError, match="9999"):
        check_rationale(draft, PAYLOAD)


def test_check_rejects_unknown_ids():
    draft = {
        "summary": "Paid.",
        "steps": [{"step": "nope", "text": "Done."}],
        "clauses": [{"id": "bogus", "text": "Cited."}],
    }
    with pytest.raises(ValueError, match="[Ss]tep"):
        check_rationale(draft, PAYLOAD)
    draft["steps"] = [{"step": "step-one", "text": "Done."}]
    with pytest.raises(ValueError, match="[Cc]lause"):
        check_rationale(draft, PAYLOAD)


def _payload_for(sample_id):
    recording = json.loads((CACHE / f"{sample_id}_photo.json").read_text(encoding="utf-8"))
    return rationale_payload(recording["inputs"], recording["output"])


@pytest.mark.parametrize(
    ("sample", "decision", "amount"),
    [("A_niseko_wrist", "PAID", 2216050), ("S2_seoul_worker_bronchitis", "PARTIAL", 22500)],
)
def test_english_cards_from_replay(sample, decision, amount):
    from claimlens.providers.replay import ReplayProvider

    card = build_rationale(sample, "photo", ReplayProvider())
    assert card["decision"] == decision
    assert card["amount_krw"] == amount
    assert card["summary"].strip()
    assert len(card["steps"]) == 5
    assert len(card["clauses"]) >= 1
    payload = _payload_for(sample)
    allowed = engine_numbers(payload)
    prose = {
        "summary": card["summary"],
        "steps": [{"text": s["text"]} for s in card["steps"]],
        "clauses": [{"text": c["text"]} for c in card["clauses"]],
    }
    assert draft_numbers(prose) <= allowed
    assert {c["id"] for c in card["clauses"]} <= {e["id"] for e in payload["evidence"]}
    assert len(card["calls"]) == 1
