"""Receipt arithmetic checks (SPEC 5.6). Deterministic, no model.

Korean bills get cell and row-sum checks; every other receipt gets a
total check: the total is positive and equals the line-amount sum.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class BillCheck:
    name: str
    expected: int | float | None
    actual: int | float | None
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


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def check_total_positive(receipt: dict[str, Any]) -> BillCheck:
    """Every receipt total is a positive printed amount."""
    total = _number_or_none(receipt.get("total_amount"))
    if total is None:
        return BillCheck("total_positive", None, None, False, "missing total_amount")
    ok = total > 0
    return BillCheck(
        "total_positive", None, total, ok, "ok" if ok else f"total {total} not positive"
    )


def check_receipt_total(receipt: dict[str, Any]) -> list[BillCheck]:
    """Arithmetic checks for non-Korean receipts: positive total, lines sum to it.

    56: re-read tax/discount/adjustment lines count toward the sum, so a
    bill with a printed tax or adjustment block can pass. Readings never
    carry that key (the reading schema is unchanged), so the first pass
    behaves exactly as before.
    """
    total = _number_or_none(receipt.get("total_amount"))
    lines = receipt.get("line_items") or []
    amounts = [_number_or_none(i.get("amount")) for i in lines]
    adjust = [_number_or_none(a.get("amount"))
              for a in receipt.get("adjustment_lines") or []]
    if any(a is None for a in amounts):
        lines_sum = BillCheck("lines_sum_total", total, None, False, "missing line amount")
    elif total is None:
        lines_sum = BillCheck("lines_sum_total", None, sum(amounts), False, "missing total")
    elif any(a is None for a in adjust):
        lines_sum = BillCheck("lines_sum_total", total, None, False,
                              "missing adjustment amount")
    else:
        found = sum(amounts) + sum(adjust)
        ok = abs(found - total) < 0.01
        lines_sum = BillCheck(
            "lines_sum_total", total, found, ok,
            "ok" if ok else f"expected {total}, read {found}",
        )
    return [check_total_positive(receipt), lines_sum,
            check_country_currency(receipt)]


# C1: every country/currency pair the pipeline has ever seen. A pair
# outside this table stops for a person instead of converting blind
# (a wrong currency is a ~147x error no amount check can catch).
COUNTRY_CURRENCY = {
    "KR": "KRW",
    "JP": "JPY",
    "US": "USD",
    "TH": "THB",
    "VN": "VND",
    "CN": "CNY",
    "FR": "EUR",
}


def check_country_currency(receipt: dict[str, Any]) -> BillCheck:
    """The receipt's country and currency form a listed pair."""
    country = receipt.get("country")
    currency = receipt.get("currency")
    if not country or not currency:
        return BillCheck("country_currency", None, None, False,
                         "missing country or currency")
    ok = COUNTRY_CURRENCY.get(country) == currency
    detail = "ok" if ok else f"{country} does not use {currency}"
    return BillCheck("country_currency", COUNTRY_CURRENCY.get(country),
                     currency, ok, detail)


def receipt_checks(receipt: dict[str, Any]) -> list[BillCheck]:
    """The check set for what was read: Korean cells, or receipt totals."""
    bill = receipt.get("kr_bill")
    if bill:
        # check_kr_bill/check_kr_lines stay byte-stable: recorded agent
        # turns are keyed on them. The cross-checks below are
        # serve/gate/verify only (C2, C1).
        return [*check_kr_bill(bill), *check_kr_lines(receipt),
                check_kr_printed_total(receipt),
                check_country_currency(receipt)]
    return check_receipt_total(receipt)


def check_kr_printed_total(receipt: dict[str, Any]) -> BillCheck:
    """C2: the printed patient total matches the patient-borne cell.

    total_amount is the patient burden as printed; for Korean bills that
    is cell 8 (환자부담 총액). A mismatch means one of the two was misread.
    """
    total = _number_or_none(receipt.get("total_amount"))
    cell8 = cell_value(receipt.get("kr_bill") or {}, 8)
    if total is None:
        return BillCheck("printed_total_8", cell8, None, False, "missing total_amount")
    if cell8 is None:
        return BillCheck("printed_total_8", None, total, False, "missing cell_8")
    ok = abs(total - cell8) < 0.01
    detail = "ok" if ok else f"expected {cell8}, read {total}"
    return BillCheck("printed_total_8", cell8, total, ok, detail)


def check_kr_lines(receipt: dict[str, Any]) -> list[BillCheck]:
    """Line-item checks for Korean receipts: present, count, and sum.

    A bill with a non-zero total but no line items fails, so the re-read
    loop runs instead of the gap passing silently.
    """
    bill = receipt.get("kr_bill") or {}
    lines = receipt.get("line_items") or []
    rows = bill.get("charge_rows") or []
    total = _number_or_none(receipt.get("total_amount"))
    gross = _int_or_none(bill.get("cell_6"))
    if lines or total == 0:
        present = BillCheck("lines_present", None, len(lines), True, "ok")
    else:
        present = BillCheck("lines_present", None, 0, False, "missing line_items")
    count_ok = len(lines) == len(rows)
    count = BillCheck(
        "lines_count",
        len(rows),
        len(lines),
        count_ok,
        "ok" if count_ok else f"expected {len(rows)}, read {len(lines)}",
    )
    amounts = [_number_or_none(i.get("amount")) for i in lines]
    # Line amounts are per-row totals across the four columns, so they sum to
    # cell 6 (진료비 총액), not to the patient-borne total.
    target = float(gross) if gross is not None else total
    if any(a is None for a in amounts):
        total_check = BillCheck("lines_sum", target, None, False, "missing line amount")
    elif target is None:
        total_check = BillCheck("lines_sum", None, sum(amounts), False, "missing total")
    else:
        found = sum(a for a in amounts if a is not None)
        ok = abs(found - target) < 0.01
        total_check = BillCheck(
            "lines_sum", target, found, ok, "ok" if ok else f"expected {target}, read {found}"
        )
    return [present, count, total_check]
