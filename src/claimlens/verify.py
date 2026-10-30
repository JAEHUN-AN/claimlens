"""Verify-and-re-read loop for receipts (SPEC 5.6). One re-read max."""

from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

from claimlens.checks import BillCheck, all_passed, receipt_checks
from claimlens.schema import LineItem, strict_schema_of

CHECK_CELLS: dict[str, list[str]] = {
    "total_6": ["cell_1", "cell_2", "cell_3", "cell_4", "cell_6"],
    "insurer_total_7": ["cell_2", "cell_5", "cell_7"],
    "patient_total_8": ["cell_1", "cell_5", "cell_3", "cell_4", "cell_8"],
    "amount_due_10": ["cell_8", "cell_9", "cell_10"],
}

LINES_CHECKS = ("lines_present", "lines_count", "lines_sum")

CELL_LABELS = {
    "cell_1": "column 1 total (본인부담금 합계)",
    "cell_2": "column 2 total (공단부담금 합계)",
    "cell_3": "column 3 total (전액본인부담 합계)",
    "cell_4": "column 4 total (비급여 합계)",
    "cell_5": "cell 5 (상한액 초과금)",
    "cell_6": "cell 6 (진료비 총액)",
    "cell_7": "cell 7 (공단부담 총액)",
    "cell_8": "cell 8 (환자부담 총액)",
    "cell_9": "cell 9 (이미 납부한 금액)",
    "cell_10": "cell 10 (납부할 금액)",
}

COL_LABELS = {1: "본인부담금", 2: "공단부담금", 3: "전액본인부담", 4: "비급여"}

CATEGORIES = (
    "consultation, emergency_fee, imaging, lab, procedure, surgery, medication, "
    "vaccination, device_purchase, health_checkup, room, admin_fee, other"
)


TOTAL_CHECKS = ("total_positive", "lines_sum_total")


def involved_cells(failed: list[BillCheck], receipt: dict[str, Any]) -> list[str]:
    """Cell keys involved in the failed checks, sorted and unique."""
    keys: set[str] = set()
    rows = (receipt.get("kr_bill") or {}).get("charge_rows") or []
    for check in failed:
        if check.name in CHECK_CELLS:
            keys.update(CHECK_CELLS[check.name])
        elif check.name.startswith("rows_sum_"):
            try:
                n = int(check.name.rsplit("_", 1)[-1])
            except ValueError:
                continue
            keys.add(f"cell_{n}")
            for i in range(len(rows)):
                keys.add(f"row_{i}_col_{n}")
        elif check.name in LINES_CHECKS:
            keys.add("line_items")
        elif check.name == "country_currency":
            pass  # C1: unfixable by re-reading cells; stops with no re-read.
        elif check.name == "printed_total_8":
            keys.update(["cell_8", "total_amount"])
        elif check.name in TOTAL_CHECKS:
            keys.add("total_amount")
    return sorted(keys)


def build_reread_model(cell_keys: list[str]) -> type[BaseModel]:
    """Tiny strict model with only the involved cells."""
    fields: dict[str, Any] = {
        key: (int | None, Field(default=None, description=f"Re-read value for {key}."))
        for key in cell_keys
        if key not in ("line_items", "total_amount")
    }
    if "line_items" in cell_keys:
        fields["line_items"] = (
            list[LineItem],
            Field(description="Re-read itemized charge table, one entry per row."),
        )
    if "total_amount" in cell_keys:
        fields["total_amount"] = (
            float | None,
            Field(default=None, description="Re-read receipt total as printed."),
        )
    return create_model("RereadCells", **fields)  # type: ignore[call-overload]


def _describe_key(key: str, receipt: dict[str, Any]) -> str:
    if key == "total_amount":
        return "the receipt total (total_amount)"
    if key == "line_items":
        rows = (receipt.get("kr_bill") or {}).get("charge_rows") or []
        return (
            f"the itemized charge table as line_items: one entry per printed row "
            f"(description, category, amount), {len(rows)} rows expected"
        )
    if key in CELL_LABELS:
        return f"{key} ({CELL_LABELS[key]})"
    if key.startswith("row_"):
        try:
            rest = key.removeprefix("row_")
            idx, _, col = rest.partition("_col_")
            i, n = int(idx), int(col)
            rows = (receipt.get("kr_bill") or {}).get("charge_rows") or []
            label = rows[i].get("label", "") if i < len(rows) else ""
            col_name = COL_LABELS.get(n, f"column {n}")
            return f"charge row {i + 1} ('{label}') column {n} ({col_name}) as {key}"
        except (ValueError, IndexError, AttributeError):
            pass
    return key


def build_reread_instructions(cell_keys: list[str], receipt: dict[str, Any]) -> str:
    """Narrow prompt naming only the failed cells."""
    if cell_keys == ["total_amount"]:
        return (
            "You previously read a receipt. "
            "Re-read ONLY the receipt total (total_amount) from the same image, "
            "copying the printed number exactly without commas. Never compute, infer, "
            "or copy from other amounts. Use null only when unreadable."
        )
    items = "; ".join(_describe_key(k, receipt) for k in cell_keys)
    text = (
        "You previously read a Korean receipt (별지 제6호서식). "
        "Re-read ONLY these cells from the same image, copying printed numbers "
        "exactly without commas. Never compute, infer, or copy from other cells. "
        f"Cells: {items}. "
        "Use 0 when the cell prints 0 or is blank (charge rows), "
        "null only when unreadable."
    )
    if "line_items" in cell_keys:
        text += (
            " For line_items, category is exactly one of: " + CATEGORIES + "."
        )
    return text


def merge_reread(
    receipt: dict[str, Any], reread: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Merge only fresh readings; never compute. Returns (merged, corrected)."""
    merged = deepcopy(receipt)
    if "kr_bill" in merged:
        merged["kr_bill"] = merged.get("kr_bill") or {}
    bill = merged.get("kr_bill") or {}
    rows = bill.get("charge_rows") or []
    corrected: list[str] = []
    for key, value in reread.items():
        if key == "line_items":
            if isinstance(value, list) and merged.get("line_items") != value:
                merged["line_items"] = value
                corrected.append(key)
            continue
        if key == "total_amount":
            if (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and value != merged.get("total_amount")):
                merged["total_amount"] = value
                corrected.append(key)
            continue
        if value is None or isinstance(value, bool):
            continue
        if not isinstance(value, int):
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            else:
                continue
        if key.startswith("cell_"):
            if bill.get(key) != value:
                bill[key] = value
                corrected.append(key)
        elif key.startswith("row_"):
            try:
                rest = key.removeprefix("row_")
                idx, _, col = rest.partition("_col_")
                i, n = int(idx), int(col)
                col_key = f"col_{n}"
                if i < len(rows) and rows[i].get(col_key) != value:
                    rows[i][col_key] = value
                    corrected.append(key)
            except (ValueError, IndexError):
                continue
    return merged, sorted(corrected)


# C5: read 1's re-read keeps the legacy "" tag so committed narrow
# re-reads still replay; read 2's re-read gets its own tag so the two
# reads can never share one re-read recording.
REREAD_READ2_TAG = ".read2"


# 56: every bill with a tax line (U3, T3) or a discount/insurance
# adjustment (U4, T5) stopped in all pairs: lines_sum_total expects
# total = sum of item lines. The reading schema stays untouched;
# instead one narrow re-read asks ONLY for those printed lines.
ADJUSTMENT_KINDS = ("tax", "discount", "adjustment")

ADJUSTMENT_SOURCE = "narrow re-read"

ADJUSTMENT_INSTRUCTIONS = (
    "You previously read a receipt whose item lines do not add up to its "
    "printed total. Re-read ONLY the printed tax, discount and adjustment "
    "lines from the same image (for example consumption-tax, service-tax, "
    "discount, insurance-adjustment or patient-responsibility lines) — "
    "never the item lines and never the total. If the receipt also prints "
    "a charges subtotal (the item total before those lines), copy it into "
    "subtotal, otherwise leave it null; never file the subtotal itself as "
    "an adjustment line. Copy each printed amount exactly with its printed "
    "sign: amounts that lower the total are negative. Return an empty list "
    "when no such line is printed. Never compute or infer."
)


class AdjustmentLine(BaseModel):
    label: str = Field(
        default="", description="Printed label of the tax/discount/adjustment line."
    )
    kind: Literal["tax", "discount", "adjustment"] = Field(
        default="adjustment", description="Which printed line this is."
    )
    amount: float = Field(description="Printed amount, signed as printed.")


class AdjustmentReread(BaseModel):
    adjustment_lines: list[AdjustmentLine] = Field(
        default_factory=list,
        description="Re-read tax/discount/adjustment lines, one entry per row.",
    )
    subtotal: float | None = Field(
        default=None,
        description="Printed charges subtotal before those lines, if shown.",
    )


def adjustment_schema() -> dict[str, Any]:
    """Strict schema with only the adjustment lines (own cache key)."""
    return strict_schema_of(AdjustmentReread)


def needs_adjustment_reread(receipt: dict[str, Any],
                            failed: list[BillCheck]) -> bool:
    """True when the only sum gap is explainable by adjustment lines.

    Non-Korean receipts with a positive printed total, numeric line
    amounts, and a failing lines_sum_total: the total re-read cannot
    help (the total is already there), so the one re-read asks for the
    tax/discount/adjustment lines instead.
    """
    if (receipt.get("kr_bill") or receipt.get("adjustment_lines")
            or receipt.get("subtotal") is not None):
        return False
    names = {c.name for c in failed}
    if "lines_sum_total" not in names or "total_positive" in names:
        return False
    gap = next(c for c in failed if c.name == "lines_sum_total")
    return gap.expected is not None and gap.actual is not None


def merge_adjustments(
    receipt: dict[str, Any], reread: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Adopt re-read adjustment lines; never compute. Returns (merged, corrected)."""
    merged = deepcopy(receipt)
    entries = reread.get("adjustment_lines") or []
    if not isinstance(entries, list):
        return merged, []
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        amount = entry.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            continue
        kind = entry.get("kind")
        normalized.append({
            "label": entry.get("label") or "",
            "kind": kind if kind in ADJUSTMENT_KINDS else "adjustment",
            "amount": float(amount),
            "source": ADJUSTMENT_SOURCE,
        })
    corrected: list[str] = []
    if normalized:
        merged["adjustment_lines"] = normalized
        corrected.append("adjustment_lines")
    subtotal = reread.get("subtotal")
    if (isinstance(subtotal, (int, float)) and not isinstance(subtotal, bool)):
        merged["subtotal"] = float(subtotal)
        corrected.append("subtotal")
    return merged, sorted(corrected)


def verify_receipt(receipt: dict[str, Any], image: Path, provider: Any,
                   cache_tag: str = "") -> dict[str, Any]:
    """Check once; on failure do one narrow re-read and check again."""
    first = receipt_checks(receipt)
    if all_passed(first):
        return {"status": "verified", "checks": first, "corrected": [], "receipt": receipt}
    failed = [c for c in first if not c.passed]
    if needs_adjustment_reread(receipt, failed):
        reread = provider.read_documents(
            [image], ADJUSTMENT_INSTRUCTIONS, adjustment_schema(),
            result_model=AdjustmentReread, cache_tag=cache_tag)
        merged, corrected = merge_adjustments(receipt, reread)
        return _rechecked(merged, corrected, failed)
    keys = involved_cells(failed, receipt)
    if not keys:
        return {
            "status": "needs_manual_check",
            "checks": first,
            "corrected": [],
            "receipt": receipt,
            "failed_before": [c.name for c in failed],
            "failing": [c.name for c in failed],
        }
    model = build_reread_model(keys)
    schema = strict_schema_of(model)
    instructions = build_reread_instructions(keys, receipt)
    reread = provider.read_documents([image], instructions, schema,
                                    result_model=model, cache_tag=cache_tag)
    merged, corrected = merge_reread(receipt, reread)
    return _rechecked(merged, corrected, failed)


def _rechecked(merged: dict[str, Any], corrected: list[str],
               failed: list[BillCheck]) -> dict[str, Any]:
    """The shared after-one-re-read verdict: pass, or stop as before."""
    second = receipt_checks(merged)
    if all_passed(second):
        return {
            "status": "verified",
            "checks": second,
            "corrected": corrected,
            "receipt": merged,
            "failed_before": [c.name for c in failed],
        }
    return {
        "status": "needs_manual_check",
        "checks": second,
        "corrected": corrected,
        "receipt": merged,
        "failed_before": [c.name for c in failed],
        "failing": [c.name for c in second if not c.passed],
    }
