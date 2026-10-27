"""Engine connection tests: pure input builders plus replay-pinned decisions."""

import pytest

from claimlens.engine import (
    adjudicate_sample,
    build_inputs,
    build_narrative,
    copay_rate_from_bill,
    replay_reading,
    to_krw,
)


def test_fx_demo_rates():
    assert to_krw(235000, "JPY") == 2216050
    assert to_krw(45000, "KRW") == 45000
    with pytest.raises(ValueError):
        to_krw(10, "XXX")


def test_narrative_uses_closed_categories_only():
    items = [
        {"category": "consultation"},
        {"category": "emergency_fee"},
        {"category": "consultation"},
        {"category": "vaccination"},
    ]
    assert build_narrative(items) == "진찰, 응급실 진료, 예방접종"


def test_copay_rate_guards():
    assert copay_rate_from_bill({"cell_1": 45000, "cell_2": 45000}) == 0.5
    assert copay_rate_from_bill({"cell_1": 0, "cell_2": 0}) is None
    assert copay_rate_from_bill({"cell_1": None, "cell_2": 10}) is None
    assert copay_rate_from_bill(None) is None


def test_a_inputs_from_pinned_reading():
    inputs = build_inputs("A_niseko_wrist", "photo", replay_reading("A_niseko_wrist", "photo"))
    assert inputs["claimed_amount_krw"] == 2216050
    assert inputs["treated_abroad"] is True
    assert inputs["diagnosis_codes"] == ["S62.0"]
    assert inputs["product"] == "기본형 해외여행 실손의료보험"
    assert inputs["institution"] is None
    assert inputs["copay_rate"] is None


def test_s2_inputs_carry_institution_and_copay():
    reading = replay_reading("S2_seoul_worker_bronchitis", "photo")
    inputs = build_inputs("S2_seoul_worker_bronchitis", "photo", reading)
    assert inputs["claimed_amount_krw"] == 45000
    assert inputs["treated_abroad"] is False
    assert inputs["institution"] == "종합병원"
    assert inputs["copay_rate"] == 0.5
    assert inputs["diagnosis_codes"] == ["J20.9"]


def test_s3_is_not_sent_to_engine(monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    envelope = adjudicate_sample("S3_us_tourist_hip_fracture", "photo")
    assert envelope["sent"] is False
    assert envelope["eligibility"]["outcome"] == "not_member_or_unknown"
    assert envelope["output"] is None


@pytest.mark.parametrize(
    ("sample", "decision", "amount"),
    [
        ("A_niseko_wrist", "PAID", 2216050),
        ("S2_seoul_worker_bronchitis", "PARTIAL", 22500),
        ("B_chiangmai_dogbite", "HUMAN_REVIEW", None),
        ("C_newyork_panic", "DENIED", None),
    ],
)
def test_replay_pins_engine_decisions(monkeypatch, sample, decision, amount):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    envelope = adjudicate_sample(sample, "photo")
    assert envelope["sent"] is True
    assert envelope["output"]["decision"] == decision
    if amount is not None:
        assert envelope["output"]["amount"] == amount
