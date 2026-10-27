"""Pure arithmetic-check tests (SPEC 5.6). No provider involved."""

import copy

import pytest

from claimlens.checks import all_passed, check_kr_bill

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
