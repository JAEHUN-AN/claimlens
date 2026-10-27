"""Pure arithmetic-check tests (SPEC 5.6). No provider involved."""

import pytest

from claimlens.checks import all_passed, check_kr_bill

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
}


def test_s2_cells_pass():
    assert all_passed(check_kr_bill(dict(S2_CELLS)))


@pytest.mark.parametrize("cell", ["cell_6", "cell_7", "cell_8", "cell_10"])
def test_altered_cell_fails(cell):
    cells = dict(S2_CELLS)
    cells[cell] += 1000
    assert not all_passed(check_kr_bill(cells))


def test_missing_cell_fails():
    cells = dict(S2_CELLS)
    cells["cell_5"] = None
    assert not all_passed(check_kr_bill(cells))
