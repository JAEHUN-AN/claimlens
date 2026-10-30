"""38 cover letter: placeholders-only drafts, reject/retry/template, pack check."""

import base64
import copy
import json
from pathlib import Path

import pytest

from claimlens.claimpack import build_pack
from claimlens.cli import main
from claimlens.letter import (
    LETTER_EST,
    TEMPLATE_LETTER,
    LetterDraft,
    LetterRejected,
    build_letter,
    check_draft,
    check_letter_numbers,
    draft_keys,
    fill_placeholders,
    letter_instructions,
    letter_retry_instructions,
    letter_schema,
    letter_values,
    record_drafts,
)
from claimlens.providers.meta import MODEL, CallRecord, MetaProvider
from claimlens.providers.replay import ReplayProvider

ROOT = Path(__file__).resolve().parent.parent

GOOD_DRAFT = (
    "Dear Claims Officer, I am {{PATIENT_NAME}}. I was treated from "
    "{{VISIT_DATES}} and paid {{TOTAL}} {{CURRENCY}}. My codes are "
    "{{DIAGNOSIS_CODES}}. I enclose {{DOCUMENTS}}."
)


def _s3_pack(variant="photo"):
    return build_pack("S3_us_tourist_hip_fracture", variant, ReplayProvider())


class _WriteStub:
    """Scripts one draft per write; records instructions for key assertions."""

    name = "stub"
    model = "stub"

    def __init__(self, drafts):
        self._drafts = list(drafts)
        self.calls = []
        self.instructions_seen = []

    def write(self, instructions, schema, result_model=None):
        self.calls.append(CallRecord(model=self.model, input_tokens=100,
                                     output_tokens=50, total_tokens=150,
                                     cost_usd=0.001))
        self.instructions_seen.append(instructions)
        assert result_model is LetterDraft
        return copy.deepcopy(self._drafts.pop(0))


def test_placeholders_only_draft_fills_from_pack():
    pack = _s3_pack()
    letter = build_letter("S3_us_tourist_hip_fracture", "photo", pack,
                          _WriteStub([{"letter": GOOD_DRAFT}]))
    assert letter["source"] == "spark"
    assert "{{" not in letter["text"]
    assert "15,000,000" in letter["text"]
    assert "Michael J. CARTER" in letter["text"]
    assert "2026-09-03 to 2026-09-09" in letter["text"]
    assert "S72.120 (KCD — the code on my certificate)" in letter["text"]
    assert ("S72.1 (WHO ICD-10) and S72.141A (ICD-10-CM) are rule-based "
            "candidates, not confirmed") in letter["text"]
    assert "hospital receipt and medical certificate" in letter["text"]


def test_stray_digits_reject_retry_then_template():
    pack = _s3_pack()
    bad = {"letter": "I paid 15000000 KRW on 2026-09-09, {{PATIENT_NAME}}."}
    stub = _WriteStub([bad, bad])
    letter = build_letter("S3_us_tourist_hip_fracture", "photo", pack, stub)
    assert letter["source"] == "template"
    assert len(stub.calls) == 2
    first, second = stub.instructions_seen
    assert first == letter_instructions("S3_us_tourist_hip_fracture", "photo")
    assert second == letter_retry_instructions("S3_us_tourist_hip_fracture", "photo")
    assert first != second  # the retry is its own cache key, never an overwrite
    assert "{{" not in letter["text"]
    assert "15,000,000" in letter["text"]


def test_retry_recovers_after_first_rejection():
    pack = _s3_pack()
    bad = {"letter": "Total 15000000 KRW for {{PATIENT_NAME}}."}
    letter = build_letter("S3_us_tourist_hip_fracture", "photo", pack,
                          _WriteStub([bad, {"letter": GOOD_DRAFT}]))
    assert letter["source"] == "spark-retry"
    assert "Michael J. CARTER" in letter["text"]


def test_unknown_placeholder_rejects():
    with pytest.raises(LetterRejected, match="PHONE"):
        check_draft("Call {{PHONE}} about {{TOTAL}}.")
    pack = _s3_pack()
    letter = build_letter("S3_us_tourist_hip_fracture", "photo", pack,
                          _WriteStub([{"letter": "Call {{PHONE}}."},
                                      {"letter": GOOD_DRAFT}]))
    assert letter["source"] == "spark-retry"


def test_stray_digit_runs_are_named():
    with pytest.raises(LetterRejected, match="15,000"):
        check_draft("I paid 15,000 won, {{PATIENT_NAME}}.")
    check_draft(GOOD_DRAFT)


def test_template_is_digit_free_and_fills_clean():
    pack = _s3_pack()
    check_draft(TEMPLATE_LETTER)
    filled = fill_placeholders(TEMPLATE_LETTER, letter_values(pack))
    assert "{{" not in filled
    check_letter_numbers(filled, pack)  # must not raise
    assert "15,000,000 KRW" in filled


def test_filled_number_missing_from_pack_rejects():
    pack = _s3_pack()
    with pytest.raises(LetterRejected, match="999999"):
        check_letter_numbers("Please pay 999999 KRW to {{PATIENT_NAME}}.", pack)
    with pytest.raises(LetterRejected, match="2027"):
        check_letter_numbers("Treated 2027-01-01, {{PATIENT_NAME}}.", pack)


LETTER_CASES = [("S3_us_tourist_hip_fracture", "photo"),
                ("S3_us_tourist_hip_fracture", "clean")]


def _mirror_without_letters(tmp_path):
    """Committed cache mirror with any letter recordings removed."""
    import shutil

    mirror = tmp_path / "cache"
    shutil.copytree(ROOT / "cache", mirror, ignore=shutil.ignore_patterns("live"))
    for sample_id, variant in LETTER_CASES:
        for key in draft_keys(sample_id, variant, MODEL).values():
            (mirror / f"{key}.json").unlink(missing_ok=True)
    return mirror


def test_missing_recording_falls_back_to_template(tmp_path, monkeypatch):
    mirror = _mirror_without_letters(tmp_path)
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(mirror))
    pack = _s3_pack()
    letter = build_letter("S3_us_tourist_hip_fracture", "photo", pack,
                          ReplayProvider())
    assert letter["source"] == "template"
    assert "Michael J. CARTER" in letter["text"]


def test_photo_and_clean_use_distinct_new_keys():
    photo = draft_keys("S3_us_tourist_hip_fracture", "photo", MODEL)
    clean = draft_keys("S3_us_tourist_hip_fracture", "clean", MODEL)
    assert photo["base"] != photo["retry"]
    assert photo["base"] != clean["base"]
    assert photo["retry"] != clean["retry"]
    schema = letter_schema()
    assert schema["required"] == ["letter"]
    assert list(schema["properties"]) == ["letter"]
    assert letter_instructions("S3_us_tourist_hip_fracture", "photo") != (
        letter_retry_instructions("S3_us_tourist_hip_fracture", "photo")
    )


def _s3_images():
    root = ROOT / "samples" / "S3_us_tourist_hip_fracture"
    return [{"name": name,
             "data": base64.b64encode((root / name).read_bytes()).decode("ascii")}
            for name in ("receipt_photo.jpg", "medical_certificate_photo.jpg")]


def _s3_person():
    scenarios = json.loads((ROOT / "samples" / "scenarios_inbound.json").read_text(
        encoding="utf-8"))["scenarios"]
    return next(s for s in scenarios if s["id"] == "S3_us_tourist_hip_fracture")[
        "person"]


def test_serve_claim_pack_carries_filled_letter(monkeypatch):
    from claimlens import serve
    from claimlens.engine import replay_reading

    class _Stub:
        name = "stub"
        model = "stub"

        def __init__(self):
            self.calls = []

        def _log(self, total):
            self.calls.append(CallRecord(model=self.model, input_tokens=total,
                                         output_tokens=0, total_tokens=total,
                                         cost_usd=None))

        def read_documents(self, images, instructions, schema, result_model=None,
                           cache_tag=""):
            self._log(100)
            return copy.deepcopy(
                replay_reading("S3_us_tourist_hip_fracture", "photo"))

        def write(self, instructions, schema, result_model=None):
            self._log(50)
            if result_model is LetterDraft:
                return {"letter": GOOD_DRAFT}
            labels = [line[2:] for line in instructions.splitlines()
                      if line.startswith("- ")]
            return {"labels": [{"ko": label, "en": label} for label in labels]}

    monkeypatch.setattr(serve, "live_provider", _Stub)
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    raw = json.dumps({"images": _s3_images(), "person": _s3_person()}).encode("utf-8")
    headers = {"host": "127.0.0.1:8000", "content_type": "application/json",
               "origin": ""}
    status, result = serve.route_post("/api/run", raw, len(raw), headers, 8000)
    assert status == 200
    assert result["result"]["badge"] == "claim_pack"
    assert result["result"]["letter_source"] == "spark"
    assert "15,000,000" in result["result"]["letter"]
    assert "Michael J. CARTER" in result["result"]["letter"]


def test_demo_pack_carries_letter_and_headings(tmp_path, monkeypatch):
    from claimlens.demo import export_demo

    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(_mirror_without_letters(tmp_path)))
    text = export_demo(tmp_path / "demo.html").read_text(encoding="utf-8")
    assert "Draft — for the patient to review and send" in text
    assert "초안 — 환자가 검토 후 발송" in text
    raw = text.split('<script id="demo-data" type="application/json">')[1]
    payload = json.loads(raw.split("</script>")[0])
    s3 = next(s for s in payload["scenes"] if s["id"] == "S3_us_tourist_hip_fracture")
    assert s3["pack"]["letter"]["source"] == "template"  # no recording yet
    assert "15,000,000" in s3["pack"]["letter"]["text"]


def test_record_letter_plan_only_prints_and_stops(capsys, tmp_path, monkeypatch):
    mirror = _mirror_without_letters(tmp_path)
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(mirror))
    before = sorted(p.name for p in mirror.glob("*.json"))
    assert main(["record-letter"]) == 0
    out = capsys.readouterr().out
    assert "2 of 2 drafts missing" in out
    assert f"{2 * LETTER_EST:.2f}" in out
    assert "Stopped before any API call" in out
    assert "claimlens demo" in out
    assert sorted(p.name for p in mirror.glob("*.json")) == before


def test_record_drafts_stores_new_keys_only(tmp_path, monkeypatch):
    from claimlens import cache as replay_cache

    mirror = _mirror_without_letters(tmp_path)
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(mirror))
    before = sorted(p.name for p in mirror.glob("*.json"))

    class _Canned:
        def __init__(self):
            from types import SimpleNamespace

            payload = json.dumps({"letter": GOOD_DRAFT})
            self.responses = SimpleNamespace(
                create=lambda **kw: SimpleNamespace(
                    output_text=payload,
                    usage=SimpleNamespace(input_tokens=60, output_tokens=40,
                                          total_tokens=100),
                )
            )

    def _factory():
        provider = MetaProvider(api_key="test-key", live=False)
        provider._client = _Canned()
        return provider

    done = record_drafts(LETTER_CASES, _factory)
    assert done["stored"] == ["S3_us_tourist_hip_fracture photo",
                              "S3_us_tourist_hip_fracture clean"]
    assert set(done["sources"].values()) == {"spark"}
    after = sorted(p.name for p in mirror.glob("*.json"))
    assert len(after) == len(before) + 2
    assert all(n in after for n in before)
    for sample_id, variant in LETTER_CASES:
        key = draft_keys(sample_id, variant, MODEL)["base"]
        assert replay_cache.cache_path(key).exists()
    rerun = record_drafts(LETTER_CASES, _factory)
    assert rerun["stored"] == []


def test_code_system_names_pass_but_other_digits_do_not():
    pack = _s3_pack()
    check_letter_numbers("Codes S72.1 (WHO ICD-10), S72.141A (ICD-10-CM).", pack)
    with pytest.raises(LetterRejected):
        check_letter_numbers("Codes S72.1 (ICD-11).", pack)


def test_instructions_make_the_patient_the_sender():
    text = letter_instructions("S3_us_tourist_hip_fracture", "photo")
    assert "first person" in text
    assert "never sign as the hospital" in text
