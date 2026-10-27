"""Receipt arithmetic check for the Korean bill (SPEC 5.6). Deterministic, no model."""

from dataclasses import dataclass
from typing import Any


@dataclass
class BillCheck:
    name: str
    expected: int | None
    actual: int | None
    passed: bool
    detail: str


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def cell_value(cells: Any, n: int) -> int | None:
    key = f"cell_{n}"
    if isinstance(cells, dict):
        value = cells.get(key)
    else:
        value = getattr(cells, key, None)
    return _int_or_none(value)


def row_value(row: Any, n: int) -> int | None:
    key = f"col_{n}"
    if isinstance(row, dict):
        value = row.get(key)
    else:
        value = getattr(row, key, None)
    return _int_or_none(value)


def charge_rows_of(cells: Any) -> list[Any] | None:
    if isinstance(cells, dict):
        rows = cells.get("charge_rows")
    else:
        rows = getattr(cells, "charge_rows", None)
    if rows is None:
        return None
    if isinstance(rows, list):
        return rows
    return None


def _check(name: str, expected: int | None, actual: int | None, cells, needs) -> BillCheck:
    missing = [f"cell_{n}" for n in needs if cells[n] is None]
    if missing:
        return BillCheck(name, expected, actual, False, f"missing {' '.join(missing)}")
    ok = expected == actual
    detail = "ok" if ok else f"expected {expected}, read {actual}"
    return BillCheck(name, expected, actual, ok, detail)


def _rows_check(n: int, expected: int | None, rows: list[Any] | None) -> BillCheck:
    name = f"rows_sum_{n}"
    if rows is None or len(rows) == 0:
        return BillCheck(name, expected, None, False, "missing charge_rows")
    if expected is None:
        return BillCheck(name, None, None, False, f"missing cell_{n}")
    values: list[int] = []
    for row in rows:
        v = row_value(row, n)
        if v is None:
            return BillCheck(name, expected, None, False, f"missing charge_rows col_{n}")
        values.append(v)
    actual = sum(values)
    ok = actual == expected
    detail = "ok" if ok else f"expected {expected}, read {actual}"
    return BillCheck(name, expected, actual, ok, detail)


def check_kr_bill(cells: Any) -> list[BillCheck]:
    """Recompute cells 6, 7, 8, 10 and column row-sums; each check is pass/fail."""
    c = {n: cell_value(cells, n) for n in range(1, 11)}

    def total(*ns: int) -> int | None:
        values = [c[n] for n in ns]
        if any(v is None for v in values):
            return None
        return sum(v for v in values if v is not None)

    exp_6 = total(1, 2, 3, 4)
    exp_7 = total(2, 5)
    if any(c[n] is None for n in (1, 5, 3, 4)):
        exp_8 = None
    else:
        exp_8 = (c[1] - c[5]) + c[3] + c[4]
    exp_10 = None if c[8] is None or c[9] is None else c[8] - c[9]
    rows = charge_rows_of(cells)
    return [
        _check("total_6", exp_6, c[6], c, (1, 2, 3, 4, 6)),
        _check("insurer_total_7", exp_7, c[7], c, (2, 5, 7)),
        _check("patient_total_8", exp_8, c[8], c, (1, 5, 3, 4, 8)),
        _check("amount_due_10", exp_10, c[10], c, (8, 9, 10)),
        _rows_check(1, c[1], rows),
        _rows_check(2, c[2], rows),
        _rows_check(3, c[3], rows),
        _rows_check(4, c[4], rows),
    ]


def all_passed(checks: list[BillCheck]) -> bool:
    return all(c.passed for c in checks)
