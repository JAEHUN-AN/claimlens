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


def cell_value(cells: Any, n: int) -> int | None:
    key = f"cell_{n}"
    if isinstance(cells, dict):
        value = cells.get(key)
    else:
        value = getattr(cells, key, None)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _check(name: str, expected: int | None, actual: int | None, cells, needs) -> BillCheck:
    missing = [f"cell_{n}" for n in needs if cells[n] is None]
    if missing:
        return BillCheck(name, expected, actual, False, f"missing {' '.join(missing)}")
    ok = expected == actual
    detail = "ok" if ok else f"expected {expected}, read {actual}"
    return BillCheck(name, expected, actual, ok, detail)


def check_kr_bill(cells: Any) -> list[BillCheck]:
    """Recompute cells 6, 7, 8, 10 from the read cells; each check is pass/fail."""
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
    return [
        _check("total_6", exp_6, c[6], c, (1, 2, 3, 4, 6)),
        _check("insurer_total_7", exp_7, c[7], c, (2, 5, 7)),
        _check("patient_total_8", exp_8, c[8], c, (1, 5, 3, 4, 8)),
        _check("amount_due_10", exp_10, c[10], c, (8, 9, 10)),
    ]


def all_passed(checks: list[BillCheck]) -> bool:
    return all(c.passed for c in checks)
