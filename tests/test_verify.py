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


def _jpy_tax_receipt():
    """T3-like: items 11,700 + consumption tax 330 = total 12,030."""
    return {
        "doc_type": "receipt", "country": "JP", "currency": "JPY",
        "total_amount": 12030.0, "service_date": "2026-09-20",
        "inpatient": False,
        "line_items": [{"description": "Consultation", "category": "consultation",
                        "amount": 5000.0},
                       {"description": "Medicine", "category": "medication",
                        "amount": 6700.0}],
    }


def test_adjustment_reread_recovers_tax_line():
    """56: a Japanese receipt passes once its tax line is re-read."""
    provider = StubProvider(
        _jpy_tax_receipt(),
        {"adjustment_lines": [{"label": "Consumption tax", "kind": "tax",
                               "amount": 330.0}]})
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"),
                            provider)
    assert result["status"] == "verified"
    assert result["corrected"] == ["adjustment_lines"]
    assert result["receipt"]["total_amount"] == 12030.0
    assert result["receipt"]["adjustment_lines"] == [
        {"label": "Consumption tax", "kind": "tax", "amount": 330.0,
         "source": "narrow re-read"}]
    assert len(provider.calls) == 2  # the initial read + one re-read
    assert "tax" in provider.last_instructions
    assert "total_amount" not in provider.last_instructions


def test_adjustment_reread_recovers_discount_line():
    """56: a US bill passes once its discount line is re-read."""
    receipt = {"doc_type": "receipt", "country": "US", "currency": "USD",
               "total_amount": 950.0, "service_date": "2026-09-21",
               "inpatient": False,
               "line_items": [{"description": "Care", "category": "consultation",
                               "amount": 1000.0}]}
    provider = StubProvider(
        receipt, {"adjustment_lines": [{"label": "Discount",
                                       "kind": "discount", "amount": -50.0}]})
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"),
                            provider)
    assert result["status"] == "verified"
    assert result["receipt"]["adjustment_lines"][0]["amount"] == -50.0


def test_adjustment_reread_recovers_insurance_adjustment():
    """56/T5: items + insurance adjustment = patient responsibility."""
    receipt = {"doc_type": "receipt", "country": "US", "currency": "USD",
               "total_amount": 1333.85, "service_date": "2026-09-26",
               "inpatient": False,
               "line_items": [{"description": label, "category": "other",
                               "amount": amount} for label, amount in
                              [("Urgent care visit", 950.0),
                               ("X-ray ankle", 620.0),
                               ("Lab tests", 240.0),
                               ("Medication", 95.5)]]}
    provider = StubProvider(
        receipt, {"adjustment_lines": [{"label": "Insurance adjustment",
                                       "kind": "adjustment",
                                       "amount": -571.65}]})
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"),
                            provider)
    assert result["status"] == "verified"
    assert result["receipt"]["total_amount"] == 1333.85


def test_adjustment_reread_still_wrong_stops():
    """56: no printed adjustment lines (or wrong ones) still stops."""
    provider = StubProvider(_jpy_tax_receipt(), {"adjustment_lines": []})
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"),
                            provider)
    assert result["status"] == "needs_manual_check"
    assert result["failing"] == ["lines_sum_total"]
    assert "adjustment_lines" not in result["receipt"]
    assert result["corrected"] == []
    wrong = StubProvider(
        _jpy_tax_receipt(),
        {"adjustment_lines": [{"label": "Consumption tax", "kind": "tax",
                               "amount": 100.0}]})
    result = verify_receipt(_read_initial(wrong), Path("receipt.jpg"), wrong)
    assert result["status"] == "needs_manual_check"
    assert result["failing"] == ["lines_sum_total"]


def test_adjustment_reread_uses_given_cache_tag():
    """56/C5: each read's adjustment re-read carries its own tag."""
    provider = StubProvider(
        _jpy_tax_receipt(),
        {"adjustment_lines": [{"label": "Consumption tax", "kind": "tax",
                               "amount": 330.0}]})
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"),
                            provider, cache_tag=".read2")
    assert result["status"] == "verified"
    assert provider.last_tag == ".read2"


def test_adjustment_reread_has_own_schema():
    """56: the adjustment call asks only for adjustment lines + subtotal."""
    from claimlens.verify import adjustment_schema

    schema = adjustment_schema()
    assert list(schema["properties"]) == ["adjustment_lines", "subtotal"]


def _t5_bill_receipt():
    """Statement with a subtotal row: items 1,905.50, total 1,333.85."""
    return {
        "doc_type": "receipt", "country": "US", "currency": "USD",
        "total_amount": 1333.85, "service_date": "2026-09-26",
        "inpatient": False,
        "line_items": [{"description": label, "category": "other",
                        "amount": amount} for label, amount in
                       [("Urgent care visit", 950.0),
                        ("X-ray ankle", 620.0),
                        ("Lab tests", 240.0),
                        ("Medication", 95.5)]],
    }


def test_adjustment_subtotal_chain_passes():
    """G1: items = subtotal and subtotal + adjustments = total verifies."""
    provider = StubProvider(
        _t5_bill_receipt(),
        {"subtotal": 1905.5,
         "adjustment_lines": [{"label": "Insurance adjustment",
                               "kind": "adjustment", "amount": -571.65}]})
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"),
                            provider)
    assert result["status"] == "verified"
    assert result["receipt"]["subtotal"] == 1905.5
    assert result["corrected"] == ["adjustment_lines", "subtotal"]


def test_adjustment_subtotal_misclassified_rejected():
    """G1: a subtotal filed as an adjustment never reconciles."""
    receipt = _t5_bill_receipt()
    mistaken = StubProvider(
        receipt, {"adjustment_lines": [{"label": "Charges subtotal",
                                       "kind": "adjustment",
                                       "amount": 1905.5}]})
    result = verify_receipt(_read_initial(mistaken), Path("receipt.jpg"),
                            mistaken)
    assert result["status"] == "needs_manual_check"
    assert result["failing"] == ["lines_sum_total"]
    double = StubProvider(
        receipt, {"subtotal": 1905.5,
                  "adjustment_lines": [{"label": "Charges subtotal",
                                        "kind": "adjustment",
                                        "amount": 1905.5}]})
    result = verify_receipt(_read_initial(double), Path("receipt.jpg"), double)
    assert result["status"] == "needs_manual_check"
    assert result["failing"] == ["lines_sum_total"]


def test_adjustment_subtotal_items_mismatch_stops():
    """G1: the chain rejects a misread item even with a true subtotal."""
    receipt = _t5_bill_receipt()
    receipt["line_items"][3]["amount"] = 955.0
    provider = StubProvider(
        receipt,
        {"subtotal": 1905.5,
         "adjustment_lines": [{"label": "Insurance adjustment",
                               "kind": "adjustment", "amount": -571.65}]})
    result = verify_receipt(_read_initial(provider), Path("receipt.jpg"),
                            provider)
    assert result["status"] == "needs_manual_check"
    assert result["failing"] == ["lines_sum_total"]


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
