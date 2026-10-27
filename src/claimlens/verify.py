"""Verify-and-re-read loop for Korean bills (SPEC 5.6). One re-read max."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, create_model

from claimlens.checks import BillCheck, all_passed, check_kr_bill, check_kr_lines
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
    return sorted(keys)


def build_reread_model(cell_keys: list[str]) -> type[BaseModel]:
    """Tiny strict model with only the involved cells."""
    fields: dict[str, Any] = {
        key: (int | None, Field(default=None, description=f"Re-read value for {key}."))
        for key in cell_keys
        if key != "line_items"
    }
    if "line_items" in cell_keys:
        fields["line_items"] = (
            list[LineItem],
            Field(description="Re-read itemized charge table, one entry per row."),
        )
    return create_model("RereadCells", **fields)  # type: ignore[call-overload]


def _describe_key(key: str, receipt: dict[str, Any]) -> str:
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
    bill = merged.get("kr_bill") or {}
    merged["kr_bill"] = bill
    rows = bill.get("charge_rows") or []
    corrected: list[str] = []
    for key, value in reread.items():
        if key == "line_items":
            if isinstance(value, list) and merged.get("line_items") != value:
                merged["line_items"] = value
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


def verify_receipt(receipt: dict[str, Any], image: Path, provider: Any) -> dict[str, Any]:
    """Check once; on failure do one narrow re-read and check again."""
    bill = receipt.get("kr_bill") or {}
    first = [*check_kr_bill(bill), *check_kr_lines(receipt)]
    if all_passed(first):
        return {"status": "verified", "checks": first, "corrected": [], "receipt": receipt}
    failed = [c for c in first if not c.passed]
    keys = involved_cells(failed, receipt)
    model = build_reread_model(keys)
    schema = strict_schema_of(model)
    instructions = build_reread_instructions(keys, receipt)
    reread = provider.read_documents([image], instructions, schema, result_model=model)
    merged, corrected = merge_reread(receipt, reread)
    second = [*check_kr_bill(merged.get("kr_bill") or {}), *check_kr_lines(merged)]
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
