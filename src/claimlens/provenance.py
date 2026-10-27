"""Number provenance: records built in Python where each number is produced.

Kinds: reading (a cell or line copied from a document), check (a formula the
code evaluated), clausegraph (an engine output or step), rule (a conversion
table row), user (an answer the user gave). The demo page renders every
covered number as a focusable span; clicking it shows this record and
highlights the operand records.
"""

from typing import Any


class ProvBuilder:
    """Collects provenance records for one demo scene."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def add(
        self,
        pid: str,
        kind: str,
        label: str,
        value: str,
        source: str,
        formula: str | None = None,
        operands: list[str] | None = None,
    ) -> str:
        if pid in self.records:
            raise ValueError(f"Duplicate provenance id {pid}.")
        self.records[pid] = {
            "kind": kind,
            "label": label,
            "value": value,
            "source": source,
            "formula": formula,
            "operands": list(operands or []),
        }
        return pid

    def num(self, pid: str, value: str) -> dict[str, str]:
        """Payload reference to a recorded number."""
        return {"v": value, "prov": pid}
