"""Eligibility rule tests (SPEC 3.5). Seven rows, deterministic, no model."""

import json
from pathlib import Path

from claimlens.eligibility import check_eligibility

SCENARIOS = Path(__file__).resolve().parents[1] / "samples" / "scenarios_inbound.json"


def _persons() -> dict[str, dict]:
    data = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    return {sc["id"]: sc["person"] for sc in data["scenarios"]}


def test_row1_workplace_s2_is_member():
    persons = _persons()
    out = check_eligibility(persons["S2_seoul_worker_bronchitis"], "2026-08-10")
    assert out["outcome"] == "nhi_member"
    assert out["rule"] == "row1_workplace"
    assert "109(2)" in out["basis"]


def test_row2_special_visa_from_entry():
    person = {
        "visa": "E-9",
        "korean_employer": False,
        "entry_date": "2026-01-01",
        "alien_registration_date": "2026-01-10",
        "premium_arrears": False,
        "work_related": False,
    }
    out = check_eligibility(person, "2026-02-01")
    assert out["outcome"] == "nhi_member"
    assert out["rule"] == "row2_special_visa"


def test_row3_short_visit_s3_is_unknown():
    persons = _persons()
    out = check_eligibility(persons["S3_us_tourist_hip_fracture"], "2026-09-03")
    assert out["outcome"] == "not_member_or_unknown"
    assert out["rule"] == "row3_six_month"


def test_row4_dependent_needs_six_months():
    person = {
        "visa": "F-3",
        "korean_employer": False,
        "entry_date": "2026-01-01",
        "alien_registration_date": "2026-01-05",
        "premium_arrears": False,
        "work_related": False,
        "is_dependent": True,
        "relation": "other",
        "age": 30,
        "overseas_days": 0,
    }
    out = check_eligibility(person, "2026-03-01")
    assert out["outcome"] == "not_member_or_unknown"
    assert out["rule"] == "row4_dependent"


def test_row5_illegal_stay_cannot_enroll():
    person = {
        "visa": "E-7",
        "korean_employer": True,
        "entry_date": "2026-01-01",
        "alien_registration_date": "2026-01-10",
        "premium_arrears": False,
        "work_related": False,
        "illegal_stay": True,
    }
    out = check_eligibility(person, "2026-08-10")
    assert out["outcome"] == "not_member_or_unknown"
    assert out["rule"] == "row5_ineligible"


def test_row6_arrears_blocks_benefits():
    persons = _persons()
    person = dict(persons["S2_seoul_worker_bronchitis"])
    person["premium_arrears"] = True
    out = check_eligibility(person, "2026-08-10")
    assert out["outcome"] == "not_member_or_unknown"
    assert out["rule"] == "row6_arrears"


def test_row7_work_injury_goes_first():
    persons = _persons()
    person = dict(persons["S2_seoul_worker_bronchitis"])
    person["work_related"] = True
    out = check_eligibility(person, "2026-08-10")
    assert out["outcome"] == "work_injury"
    assert out["rule"] == "row7_work_injury"


def test_basis_text_is_english():
    persons = _persons()
    out = check_eligibility(persons["S2_seoul_worker_bronchitis"], "2026-08-10")
    assert out["basis"].isascii()
    assert "Legal basis" in out["basis"]
