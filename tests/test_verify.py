"""Verify-and-re-read loop tests (SPEC 5.6). Stub provider, no network."""

import copy
from pathlib import Path

from claimlens.checks import all_passed, check_kr_bill
from claimlens.schema import strict_schema_of
from claimlens.verify import (
    build_reread_instructions,
    build_reread_model,
    involved_cells,
    merge_reread,
    verify_bill,
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


class StubProvider:
    """Returns the initial bill first, then the canned re-read values."""

    def __init__(self, initial_bill, reread_values):
        self.name = "stub"
        self.model = "stub"
        self.calls: list[dict] = []
        self.initial_bill = initial_bill
        self.reread_values = reread_values
        self.last_instructions = ""

    def read_documents(self, images, instructions, schema, result_model=None):
        self.calls.append({"model": self.model, "input_tokens": 100, "output_tokens": 50})
        if result_model is None or result_model.__name__ == "ReadingResult":
            return {"documents": [{"kr_bill": copy.deepcopy(self.initial_bill)}]}
        self.last_instructions = instructions
        return dict(self.reread_values)


def test_reread_fixes_wrong_cell():
    wrong = copy.deepcopy(GOOD_BILL)
    wrong["cell_8"] = 999
    assert not all_passed(check_kr_bill(wrong))
    reread = {
        "cell_1": 100,
        "cell_3": 0,
        "cell_4": 0,
        "cell_5": 0,
        "cell_8": 100,
        "cell_9": 0,
        "cell_10": 100,
    }
    provider = StubProvider(wrong, reread)
    initial = provider.read_documents(
        [Path("receipt.jpg"), Path("cert.jpg")], "full instructions", {}
    )
    bill = initial["documents"][0]["kr_bill"]
    result = verify_bill(bill, Path("receipt.jpg"), provider)
    assert result["status"] == "verified"
    assert result["corrected"] == ["cell_8"]
    assert result["bill"]["cell_8"] == 100
    assert len(provider.calls) == 2
    assert "cell_8" in provider.last_instructions
    assert "cell_6" not in provider.last_instructions


def test_reread_still_wrong_needs_manual_check():
    wrong = copy.deepcopy(GOOD_BILL)
    wrong["cell_8"] = 999
    reread = {
        "cell_1": 100,
        "cell_3": 0,
        "cell_4": 0,
        "cell_5": 0,
        "cell_8": 999,
        "cell_9": 0,
        "cell_10": 100,
    }
    provider = StubProvider(wrong, reread)
    initial = provider.read_documents(
        [Path("receipt.jpg"), Path("cert.jpg")], "full instructions", {}
    )
    bill = initial["documents"][0]["kr_bill"]
    result = verify_bill(bill, Path("receipt.jpg"), provider)
    assert result["status"] == "needs_manual_check"
    assert "patient_total_8" in result["failing"]
    assert len(provider.calls) == 2


def test_verified_without_reread_when_checks_pass():
    provider = StubProvider(copy.deepcopy(GOOD_BILL), {})
    result = verify_bill(copy.deepcopy(GOOD_BILL), Path("receipt.jpg"), provider)
    assert result["status"] == "verified"
    assert result["corrected"] == []
    assert len(provider.calls) == 0


def test_involved_cells_and_tiny_schema_cover_only_failed():
    wrong = copy.deepcopy(GOOD_BILL)
    wrong["cell_8"] = 999
    failed = [c for c in check_kr_bill(wrong) if not c.passed]
    keys = involved_cells(failed, wrong)
    assert "cell_8" in keys
    assert "cell_6" not in keys
    model = build_reread_model(keys)
    schema = strict_schema_of(model)
    assert sorted(schema["properties"]) == sorted(keys)
    text = build_reread_instructions(keys, wrong)
    assert "cell_8" in text


def test_merge_never_computes():
    bill = copy.deepcopy(GOOD_BILL)
    bill["cell_8"] = 999
    merged, corrected = merge_reread(bill, {"cell_8": 100, "cell_6": 300})
    assert merged["cell_8"] == 100
    assert corrected == ["cell_8"]
    merged2, corrected2 = merge_reread(bill, {"cell_8": None})
    assert merged2["cell_8"] == 999
    assert corrected2 == []
