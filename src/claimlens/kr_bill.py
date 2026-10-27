"""Korean bill reading schema: cells 1-10, rows, visit, period (SPEC 3.4)."""

from typing import Literal

from pydantic import BaseModel, Field

KrInstitution = Literal["의원급·보건기관", "병원급", "종합병원", "상급종합병원"]

KrVisit = Literal["외래", "입원"]


class KrChargeRow(BaseModel):
    """One printed charge row with its four amount columns."""

    label: str = Field(description="Printed row label, copied exactly.")
    col_1: int | None = Field(default=None, description="Row cell in column 1 (본인부담금).")
    col_2: int | None = Field(default=None, description="Row cell in column 2 (공단부담금).")
    col_3: int | None = Field(default=None, description="Row cell in column 3 (전액본인부담).")
    col_4: int | None = Field(default=None, description="Row cell in column 4 (비급여).")


class KrBill(BaseModel):
    """Circled cells of the Korean receipt form (별지 제6호서식), copied by number."""

    cell_1: int | None = Field(default=None, description="Cell 1: 본인부담금 column total (합계 row).")
    cell_2: int | None = Field(default=None, description="Cell 2: 공단부담금 column total (합계 row).")
    cell_3: int | None = Field(default=None, description="Cell 3: 전액본인부담 column total (합계 row).")
    cell_4: int | None = Field(default=None, description="Cell 4: 비급여 column total (합계 row).")
    cell_5: int | None = Field(default=None, description="Cell 5: 상한액 초과금.")
    cell_6: int | None = Field(default=None, description="Cell 6: 진료비 총액.")
    cell_7: int | None = Field(default=None, description="Cell 7: 공단부담 총액.")
    cell_8: int | None = Field(default=None, description="Cell 8: 환자부담 총액.")
    cell_9: int | None = Field(default=None, description="Cell 9: 이미 납부한 금액.")
    cell_10: int | None = Field(default=None, description="Cell 10: 납부할 금액.")
    institution_type: KrInstitution | None = Field(
        default=None, description="Checked 요양기관 종류 box, exactly as labeled."
    )
    patient_type: str | None = Field(default=None, description="환자구분 text (e.g. 건강보험).")
    visit: KrVisit | None = Field(default=None, description="Checked visit box: 외래 or 입원.")
    period_from: str | None = Field(
        default=None, description="Treatment period start as YYYY-MM-DD, or null."
    )
    period_to: str | None = Field(
        default=None, description="Treatment period end as YYYY-MM-DD, or null."
    )
    charge_rows: list[KrChargeRow] = Field(
        default_factory=list, description="One entry per printed charge row, in order."
    )
