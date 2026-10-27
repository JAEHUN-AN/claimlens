"""Claim Pack tests: translation merge plus S3 pack from replay."""

import pytest

from claimlens.claimpack import (
    POLICY_LINE,
    build_pack,
    format_html,
    format_markdown,
    translate_labels,
)


class StubWriter:
    name = "stub"
    model = "stub"

    def __init__(self, pairs):
        self.pairs = pairs
        self.calls: list[dict] = []

    def write(self, instructions, schema, result_model=None):
        self.calls.append({"model": self.model})
        return {"labels": [{"ko": ko, "en": en} for ko, en in self.pairs]}


def test_translate_merges_by_korean_label():
    provider = StubWriter([("진찰료", "Consultation fee"), ("식대", "Meals")])
    table = translate_labels(["식대", "진찰료"], provider)
    assert table == {"식대": "Meals", "진찰료": "Consultation fee"}


def test_translate_fails_loud_on_missing_label():
    provider = StubWriter([("진찰료", "Consultation fee")])
    with pytest.raises(ValueError, match="식대"):
        translate_labels(["진찰료", "식대"], provider)


def test_pack_refuses_member_cases():
    with pytest.raises(ValueError, match="without an applicable policy"):
        build_pack("S2_seoul_worker_bronchitis", "photo", StubWriter([]))


def test_s3_pack_markdown_from_replay():
    from claimlens.providers.replay import ReplayProvider

    pack = build_pack("S3_us_tourist_hip_fracture", "photo", ReplayProvider())
    assert len(pack["items"]) == 12
    assert pack["total_krw"] == 15000000
    assert sum(i["amount"] for i in pack["items"]) == 15000000
    assert pack["checks_passed"] is True
    assert pack["codes"]["kcd"] == "S72.120"
    assert pack["codes"]["who"] == "S72.1"
    assert pack["codes"]["cm"]["chosen"] == "S72.141A"
    assert len(pack["calls"]) == 1
    text = format_markdown(pack)
    assert POLICY_LINE in text
    assert "S72.120" in text and "S72.1" in text and "S72.141A" in text
    assert "lesser trochanter" in text
    assert "15,000,000" in text
    assert "not a certified translation" in text
    assert "clinical estimate" not in text


def test_s3_pack_html_from_replay():
    from claimlens.providers.replay import ReplayProvider

    pack = build_pack("S3_us_tourist_hip_fracture", "photo", ReplayProvider())
    page = format_html(pack)
    assert page.startswith("<!DOCTYPE html>")
    assert page.rstrip().endswith("</html>")
    assert POLICY_LINE in page
    assert "S72.141A" in page
    assert "15,000,000" in page


def test_clinical_estimate_warning_branch():
    pack = {
        "sample": "S3_us_tourist_hip_fracture",
        "variant": "photo",
        "patient": {"name": "N", "date_of_birth": "", "passport": "", "patient_id": ""},
        "visit": {"hospital": "H", "inpatient": True, "period_from": "a", "period_to": "b"},
        "diagnosis": {"label": "L", "final": False},
        "codes": {"kcd": "S72.120", "who": "S72.1", "attribute": "closed",
                  "cm": {"chosen": "S72.141A", "questions": []}, "pitfall": None,
                  "disclaimer": "d"},
        "items": [],
        "total_krw": 0,
        "checks_passed": True,
        "policy_line": POLICY_LINE,
        "calls": [],
    }
    assert "clinical estimate" in format_markdown(pack)
    assert "clinical estimate" in format_html(pack)
