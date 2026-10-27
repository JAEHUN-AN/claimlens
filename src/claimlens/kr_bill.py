"""Korean bill reading schema: cells 1-10, institution checkbox, patient type (SPEC 3.4)."""

from typing import Literal

from pydantic import BaseModel, Field

KrInstitution = Literal["의원급·보건기관", "병원급", "종합병원", "상급종합병원"]


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
