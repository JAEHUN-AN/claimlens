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


def test_s2_card_shows_deductible_match():
    from claimlens.providers.replay import ReplayProvider
    from claimlens.rationale import format_card

    card = build_rationale("S2_seoul_worker_bronchitis", "photo", ReplayProvider())
    assert card["deductible"] == {
        "terms": [20000, 9000, 22500],
        "ours": 22500,
        "engine": 22500,
        "match": True,
    }
    text = format_card(card)
    assert "max(20,000, 9,000, 22,500) = 22,500 — matches the engine" in text


def test_abroad_card_has_no_deductible_section():
    from claimlens.providers.replay import ReplayProvider
    from claimlens.rationale import format_card

    card = build_rationale("A_niseko_wrist", "photo", ReplayProvider())
    assert card["deductible"] is None
    assert "Deductible check" not in format_card(card)


def test_deductible_mismatch_flags_without_replacing():
    from claimlens.rationale import compute_deductible, format_deductible

    check = compute_deductible(45000, "종합병원", 0.5, 20000)
    assert check is not None and check["match"] is False
    text = format_deductible(check)
    assert "22,500 vs engine 20,000" in text
    assert "FLAGGED" in text and "engine amount stands" in text


def test_flat_term_follows_institution():
    from claimlens.rationale import compute_deductible

    assert compute_deductible(10000, "상급종합병원", 0.5, 0)["terms"][0] == 20000
    assert compute_deductible(10000, "병원급", 0.5, 0)["terms"][0] == 10000
    assert compute_deductible(10000, None, 0.5, 0) is None
    assert compute_deductible(10000, "종합병원", None, 0) is None


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
