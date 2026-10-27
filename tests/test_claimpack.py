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


def test_s3_pii_lines_carry_check_mark():
    from claimlens.providers.replay import ReplayProvider

    pack = build_pack("S3_us_tourist_hip_fracture", "photo", ReplayProvider())
    text = format_markdown(pack)
    assert text.count("check against your passport/ID") == 4
    assert "A0000000 — check against your passport/ID" in text
    page = format_html(pack)
    assert page.count("check against your passport/ID") == 4


def test_s3_pack_vietnamese_from_replay():
    from claimlens.providers.replay import ReplayProvider

    en = build_pack("S3_us_tourist_hip_fracture", "photo", ReplayProvider())
    vi = build_pack("S3_us_tourist_hip_fracture", "photo", ReplayProvider(), lang="vi")
    assert vi["lang"] == "vi"
    assert len(vi["items"]) == 12
    assert [i["amount"] for i in vi["items"]] == [i["amount"] for i in en["items"]]
    assert vi["total_krw"] == en["total_krw"] == 15000000
    assert vi["codes"] == en["codes"]
    assert vi["visit"] == en["visit"]
    assert vi["sentences"]["policy_line"] != POLICY_LINE
    assert all(i["label"] and i["label"] != i["label_ko"] for i in vi["items"])
    text = format_markdown(vi)
    assert "15,000,000" in text and "S72.141A" in text
    assert "# Claim Pack" not in text
    page = format_html(vi)
    assert '<html lang="vi">' in page
    assert "15,000,000" in page


def test_pack_rejects_unknown_language():
    from claimlens.providers.replay import ReplayProvider

    with pytest.raises(ValueError, match="Unsupported"):
        build_pack("S3_us_tourist_hip_fracture", "photo", ReplayProvider(), lang="ja")


def test_translate_pack_rejects_missing_keys():
    from claimlens.packlang import translate_pack

    class StubPackWriter:
        def write(self, instructions, schema, result_model=None):
            return {"labels": [{"ko": "식대", "text": "Meals"}], "sentences": []}

    with pytest.raises(ValueError, match="sentences"):
        translate_pack("vi", ["식대"], StubPackWriter())


def test_claimpack_cli_lang_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    from claimlens.cli import main

    target = tmp_path / "pack_vi.md"
    args = ["claimpack", "S3_us_tourist_hip_fracture", "--lang", "vi", "--output", str(target)]
    assert main(args) == 0
    body = target.read_text(encoding="utf-8")
    assert "15,000,000" in body
    assert "# Claim Pack" not in body


def test_conflicting_pii_shows_both_readings():
    from claimlens.claimpack import _pii_line, pii_conflicts

    docs = [
        {"doc_type": "receipt", "pii": [{"kind": "name", "value": "AAA"}]},
        {"doc_type": "medical_certificate", "pii": [{"kind": "name", "value": "BBB"}]},
    ]
    found = pii_conflicts(docs)
    assert found == {"name": [["receipt", "AAA"], ["certificate", "BBB"]]}
    line = _pii_line("Name", "AAA", found["name"])
    assert "AAA (receipt)" in line and "BBB (certificate)" in line
    assert "differs between documents" in line


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
