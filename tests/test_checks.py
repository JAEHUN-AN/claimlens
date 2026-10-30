"""Pure arithmetic-check tests (SPEC 5.6). No provider involved."""

import copy

import pytest

from claimlens.checks import all_passed, check_kr_bill, receipt_checks

S2_ROWS = [
    {"label": "label-a", "col_1": 9000, "col_2": 9000, "col_3": 0, "col_4": 0},
    {"label": "label-b", "col_1": 18000, "col_2": 18000, "col_3": 0, "col_4": 0},
    {"label": "label-c", "col_1": 12000, "col_2": 12000, "col_3": 0, "col_4": 0},
    {"label": "label-d", "col_1": 3000, "col_2": 3000, "col_3": 0, "col_4": 0},
    {"label": "label-e", "col_1": 3000, "col_2": 3000, "col_3": 0, "col_4": 0},
]

S2_CELLS = {
    "cell_1": 45000,
    "cell_2": 45000,
    "cell_3": 0,
    "cell_4": 0,
    "cell_5": 0,
    "cell_6": 90000,
    "cell_7": 45000,
    "cell_8": 45000,
    "cell_9": 0,
    "cell_10": 45000,
    "charge_rows": S2_ROWS,
}


def test_s2_cells_pass():
    assert all_passed(check_kr_bill(copy.deepcopy(S2_CELLS)))


@pytest.mark.parametrize("cell", ["cell_6", "cell_7", "cell_8", "cell_10"])
def test_altered_cell_fails(cell):
    cells = copy.deepcopy(S2_CELLS)
    cells[cell] += 1000
    assert not all_passed(check_kr_bill(cells))


def test_missing_cell_fails():
    cells = copy.deepcopy(S2_CELLS)
    cells["cell_5"] = None
    assert not all_passed(check_kr_bill(cells))


def test_altered_row_fails():
    cells = copy.deepcopy(S2_CELLS)
    cells["charge_rows"][0]["col_1"] += 1000
    checks = check_kr_bill(cells)
    failed = [c for c in checks if not c.passed]
    assert any(c.name == "rows_sum_1" for c in failed)


def test_missing_rows_fails():
    cells = copy.deepcopy(S2_CELLS)
    cells["charge_rows"] = []
    assert not all_passed(check_kr_bill(cells))


def _s2_like_receipt(total=45000.0):
    rows = copy.deepcopy(S2_CELLS)["charge_rows"]
    lines = [
        {"description": r["label"], "category": "other",
         "amount": r["col_1"] + r["col_2"] + r["col_3"] + r["col_4"]}
        for r in rows
    ]
    return {"country": "KR", "currency": "KRW", "total_amount": total,
            "kr_bill": copy.deepcopy(S2_CELLS), "line_items": lines}


def test_kr_printed_total_agrees_with_cell_8():
    """C2: the printed patient total is cross-checked against cell 8."""
    checks = receipt_checks(_s2_like_receipt())
    assert all_passed(checks)
    assert "printed_total_8" in [c.name for c in checks]


def test_kr_printed_total_mismatch_fails():
    """C2: total_amount disagreeing with cell 8 fails loudly."""
    checks = receipt_checks(_s2_like_receipt(total=45001.0))
    failed = [c.name for c in checks if not c.passed]
    assert failed == ["printed_total_8"]


def test_kr_printed_total_missing_total_fails():
    """C2: a missing printed total cannot silently pass."""
    checks = receipt_checks(_s2_like_receipt(total=None))
    failed = [c.name for c in checks if not c.passed]
    assert failed == ["printed_total_8"]


def _plain_receipt(country="JP", currency="JPY"):
    return {"country": country, "currency": currency, "total_amount": 100.0,
            "line_items": [{"description": "care", "category": "other",
                            "amount": 100.0}]}


def test_country_currency_known_pairs_pass():
    """C1: listed country/currency pairs pass on both receipt kinds."""
    assert all_passed(receipt_checks(_plain_receipt("JP", "JPY")))
    assert all_passed(receipt_checks(_plain_receipt("KR", "KRW")))
    assert "country_currency" in [c.name for c in receipt_checks(
        _plain_receipt("JP", "JPY"))]


def test_country_currency_mismatch_fails():
    """C1: JPY read on a JP receipt never matches USD."""
    checks = receipt_checks(_plain_receipt("JP", "USD"))
    assert [c.name for c in checks if not c.passed] == ["country_currency"]


def test_country_currency_missing_or_unknown_fails():
    """C1: a missing or unlisted pair stops instead of converting blind."""
    assert [c.name for c in receipt_checks(_plain_receipt("JP", None))
            if not c.passed] == ["country_currency"]
    assert [c.name for c in receipt_checks(_plain_receipt(None, "JPY"))
            if not c.passed] == ["country_currency"]
    assert [c.name for c in receipt_checks(_plain_receipt("XX", "XXX"))
            if not c.passed] == ["country_currency"]
