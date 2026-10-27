"""Reading result schema (SPEC 3.1) and strict JSON Schema export (SPEC 3.2)."""

import copy
from typing import Any, Literal

from pydantic import BaseModel, Field

from claimlens.kr_bill import KrBill

DocType = Literal["receipt", "medical_certificate", "other"]

LineCategory = Literal[
    "consultation",
    "emergency_fee",
    "imaging",
    "lab",
    "procedure",
    "surgery",
    "medication",
    "vaccination",
    "device_purchase",
    "health_checkup",
    "room",
    "admin_fee",
    "other",
]

DiagSystem = Literal["ICD-10", "ICD-10-CM", "unknown"]

PiiKind = Literal["name", "date_of_birth", "passport", "patient_id", "address", "phone"]


class LineItem(BaseModel):
    description: str = Field(description="Printed line description, transcribed exactly.")
    category: LineCategory = Field(description="Exactly one of the 13 closed categories.")
    amount: float = Field(description="Printed line amount in the document currency.")


class Diagnosis(BaseModel):
    code: str = Field(description="Printed diagnosis code, exactly as printed, or ''.")
    system: DiagSystem = Field(description="Code system of the printed code.")
    label: str = Field(description="Printed diagnosis label.")
    external_cause: str = Field(
        default="", description="Printed external-cause note, or '' when absent."
    )


class Pii(BaseModel):
    kind: PiiKind = Field(description="Kind of personal data.")
    value: str = Field(description="Printed value, transcribed exactly.")


class ExtractedDocument(BaseModel):
    doc_type: DocType = Field(description="Receipt, medical certificate, or other.")
    country: str = Field(default="", description="ISO 3166-1 alpha-2 code of the hospital country.")
    provider_name: str = Field(default="", description="Hospital name as printed.")
    service_date: str | None = Field(
        default=None, description="Visit or issue date as YYYY-MM-DD, or null."
    )
    inpatient: bool = Field(default=False, description="True only for an overnight admission.")
    hospital_days: int = Field(default=0, description="Nights admitted; 0 for outpatient.")
    currency: str = Field(default="", description="ISO 4217 code; '' for medical certificates.")
    total_amount: float | None = Field(
        default=None, description="Patient total burden as printed; null for certificates."
    )
    diagnoses: list[Diagnosis] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    pii: list[Pii] = Field(default_factory=list)
    kr_bill: KrBill | None = Field(
        default=None, description="Circled cells; set only for Korean 별지 제6호서식 receipts."
    )


class ReadingResult(BaseModel):
    documents: list[ExtractedDocument] = Field(description="One entry per image, in image order.")


def strict_schema_of(model: type[BaseModel]) -> dict[str, Any]:
    """Return the strict JSON Schema form of a pydantic model.

    Every object gets additionalProperties false, every key lands in required,
    $refs are inlined, and title/default keys are dropped.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].rsplit("/", 1)[-1]
                return resolve(copy.deepcopy(defs[name]))
            out = {k: resolve(v) for k, v in node.items() if k not in ("title", "default")}
            combo = out.pop("allOf", None)
            if isinstance(combo, list) and len(combo) == 1 and isinstance(combo[0], dict):
                out = {**combo[0], **out}
            elif combo is not None:
                out["allOf"] = combo
            if out.get("type") == "object" or "properties" in out:
                out["additionalProperties"] = False
                if "properties" in out:
                    out["required"] = sorted(out["properties"])
            return out
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(raw)
