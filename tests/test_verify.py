"""Verify-and-re-read loop tests (SPEC 5.6). Stub provider, no network."""

import copy
from pathlib import Path

from claimlens.checks import all_passed, check_kr_bill, check_kr_lines
from claimlens.schema import strict_schema_of
from claimlens.verify import (
    build_reread_instructions,
    build_reread_model,
    involved_cells,
    merge_reread,
    verify_receipt,
)

GOOD_BILL = {
    "cell_1": 100,
    "cell_2": 200,
    "cell_3": 0,
    "cell_4": 0,
    "cell_5": 0,
    "cell_6": 300,
    "cell_7": 200,
    "cell_8": 100,
    "cell_9": 0,
    "cell_10": 100,
    "charge_rows": [
        {"label": "row-a", "col_1": 100, "col_2": 200, "col_3": 0, "col_4": 0},
    ],
}

GOOD_RECEIPT = {
    "country": "KR",
    "currency": "KRW",
    "total_amount": 100,
    "line_items": [{"description": "row-a", "category": "lab", "amount": 300}],
    "kr_bill": GOOD_BILL,
}


class StubProvider:
    """Returns the initial receipt first, then the canned re-read values."""

    def __init__(self, initial_receipt, reread_values):
        self.name = "stub"
        self.model = "stub"
        self.calls: list[dict] = []
        self.initial_receipt = initial_receipt
        self.reread_values = reread_values
        self.last_instructions = ""

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self.calls.append({"model": self.model, "input_tokens": 100, "output_tokens": 50})
        if result_model is None or result_model.__name__ == "ReadingResult":
            return {"documents": [copy.deepcopy(self.initial_receipt)]}
        self.last_instructions = instructions
        self.last_tag = cache_tag
        return copy.deepcopy(self.reread_values)


def _read_initial(provider):
    initial = provider.read_documents(
        [Path("receipt.jpg"), Path("cert.jpg")], "full instructions", {}
    )
    return initial["documents"][0]


def test_reread_fixes_wrong_cell():
    receipt = copy.deepcopy(GOOD_RECEIPT)
    receipt["kr_bill"]["cell_8"] = 999
    assert not all_passed(check_kr_bill(receipt["kr_bill"]))
    reread = {
        "cell_1": 100,
        "cell_3": 0,
        "cell_4": 0,
        "cell_5": 0,
        "cell_8": 100,
        "cell_9": 0,
        "cell_10": 100,
    }
    provider = StubProvider(receipt, reread)
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"), provider)
    assert result["status"] == "verified"
    assert result["corrected"] == ["cell_8"]
    assert result["receipt"]["kr_bill"]["cell_8"] == 100
    assert len(provider.calls) == 2
    assert "cell_8" in provider.last_instructions
    assert "cell_6" not in provider.last_instructions


def test_reread_still_wrong_needs_manual_check():
    receipt = copy.deepcopy(GOOD_RECEIPT)
    receipt["kr_bill"]["cell_8"] = 999
    reread = {
        "cell_1": 100,
        "cell_3": 0,
        "cell_4": 0,
        "cell_5": 0,
        "cell_8": 999,
        "cell_9": 0,
        "cell_10": 100,
    }
    provider = StubProvider(receipt, reread)
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"), provider)
    assert result["status"] == "needs_manual_check"
    assert "patient_total_8" in result["failing"]
    assert len(provider.calls) == 2


def test_verified_without_reread_when_checks_pass():
    provider = StubProvider(copy.deepcopy(GOOD_RECEIPT), {})
    result = verify_receipt(copy.deepcopy(GOOD_RECEIPT), Path("receipt.jpg"), provider)
    assert result["status"] == "verified"
    assert result["corrected"] == []
    assert len(provider.calls) == 0


def test_country_currency_failure_stops_without_reread():
    """C1: a bad country/currency pair is unfixable by re-reading cells."""
    receipt = copy.deepcopy(GOOD_RECEIPT)
    receipt["currency"] = "USD"
    provider = StubProvider(receipt, {})
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"), provider)
    assert result["status"] == "needs_manual_check"
    assert result["failing"] == ["country_currency"]
    assert len(provider.calls) == 1  # the initial read only; no re-read sent


def test_involved_cells_and_tiny_schema_cover_only_failed():
    receipt = copy.deepcopy(GOOD_RECEIPT)
    receipt["kr_bill"]["cell_8"] = 999
    failed = [c for c in check_kr_bill(receipt["kr_bill"]) if not c.passed]
    keys = involved_cells(failed, receipt)
    assert "cell_8" in keys
    assert "cell_6" not in keys
    model = build_reread_model(keys)
    schema = strict_schema_of(model)
    assert sorted(schema["properties"]) == sorted(keys)
    text = build_reread_instructions(keys, receipt)
    assert "cell_8" in text


def test_merge_never_computes():
    receipt = copy.deepcopy(GOOD_RECEIPT)
    receipt["kr_bill"]["cell_8"] = 999
    merged, corrected = merge_reread(receipt, {"cell_8": 100, "cell_6": 300})
    assert merged["kr_bill"]["cell_8"] == 100
    assert corrected == ["cell_8"]
    merged2, corrected2 = merge_reread(receipt, {"cell_8": None})
    assert merged2["kr_bill"]["cell_8"] == 999
    assert corrected2 == []


def test_empty_lines_fail_lines_checks():
    receipt = copy.deepcopy(GOOD_RECEIPT)
    receipt["line_items"] = []
    failed = [c.name for c in check_kr_lines(receipt) if not c.passed]
    assert failed == ["lines_present", "lines_count", "lines_sum"]


def test_lines_checks_pass_when_present_and_matching():
    assert all_passed(check_kr_lines(copy.deepcopy(GOOD_RECEIPT)))


def test_reread_recovers_line_items():
    receipt = copy.deepcopy(GOOD_RECEIPT)
    receipt["line_items"] = []
    reread = {"line_items": [{"description": "row-a", "category": "lab", "amount": 300}]}
    provider = StubProvider(receipt, reread)
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"), provider)
    assert result["status"] == "verified"
    assert result["corrected"] == ["line_items"]
    assert len(result["receipt"]["line_items"]) == 1
    assert len(provider.calls) == 2
    assert "line_items" in provider.last_instructions


def test_reread_without_lines_stays_manual():
    receipt = copy.deepcopy(GOOD_RECEIPT)
    receipt["line_items"] = []
    provider = StubProvider(receipt, {"line_items": []})
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"), provider)
    assert result["status"] == "needs_manual_check"
    assert "lines_present" in result["failing"]
    assert len(provider.calls) == 2


def test_reread_uses_given_cache_tag():
    """C5: the narrow re-read carries its own read's tag (read independence)."""
    receipt = copy.deepcopy(GOOD_RECEIPT)
    receipt["kr_bill"]["cell_8"] = 999
    reread = {"cell_8": 100}
    provider = StubProvider(receipt, reread)
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"), provider,
                            cache_tag=".read2")
    assert result["status"] == "verified"
    assert provider.last_tag == ".read2"


def test_s3_clean_recovers_lines_through_reread():
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.providers.replay import ReplayProvider
    from claimlens.reader import reading_schema, resolve_sample_images

    sample = Path(__file__).resolve().parents[1] / "samples" / "S3_us_tourist_hip_fracture"
    images = resolve_sample_images(sample, "clean")
    provider = ReplayProvider()
    reading = provider.read_documents(images, READING_INSTRUCTIONS, reading_schema())
    receipt = reading["documents"][0]
    assert receipt["line_items"] == []
    result = verify_receipt(receipt, images[0], provider)
    assert result["status"] == "verified"
    assert result["corrected"] == ["line_items"]
    assert len(result["receipt"]["line_items"]) == 12
    assert sum(i["amount"] for i in result["receipt"]["line_items"]) == 15000000
    assert len(provider.calls) == 2
