"""Replay-mode reading tests: recorded Spark responses, no network, no key."""

from pathlib import Path

import pytest

from claimlens.checks import all_passed, check_kr_bill
from claimlens.reader import read_sample

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


@pytest.fixture(autouse=True)
def replay(monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")


def test_a_niseko_total_and_document_order():
    envelope = read_sample(SAMPLES / "A_niseko_wrist", "photo")
    docs = envelope["result"]["documents"]
    assert [d["doc_type"] for d in docs] == ["receipt", "medical_certificate"]
    receipt = docs[0]
    assert receipt["currency"] == "JPY"
    assert receipt["total_amount"] == 235000
    assert len(receipt["line_items"]) == 6
    assert sum(i["amount"] for i in receipt["line_items"]) == 235000
    assert docs[1]["diagnoses"][0]["code"] == "S62.0"


def test_s2_cells_and_institution():
    envelope = read_sample(SAMPLES / "S2_seoul_worker_bronchitis", "photo")
    receipt = envelope["result"]["documents"][0]
    bill = receipt["kr_bill"]
    assert bill is not None
    assert [bill[f"cell_{n}"] for n in range(1, 11)] == [
        45000,
        45000,
        0,
        0,
        0,
        90000,
        45000,
        45000,
        0,
        45000,
    ]
    assert bill["institution_type"] == "종합병원"
    assert bill["patient_type"] == "건강보험"


def test_s2_visit_period_rows_and_cert():
    envelope = read_sample(SAMPLES / "S2_seoul_worker_bronchitis", "photo")
    docs = envelope["result"]["documents"]
    bill = docs[0]["kr_bill"]
    assert bill["visit"] == "외래"
    assert bill["period_from"] == "2026-08-10"
    assert bill["period_to"] == "2026-08-10"
    assert len(bill["charge_rows"]) == 5
    assert sum(r["col_1"] for r in bill["charge_rows"]) == 45000
    assert sum(r["col_2"] for r in bill["charge_rows"]) == 45000
    cert = docs[1]
    assert cert["diagnoses"][0]["code"] == "J20.9"
    assert cert["diagnoses"][0]["final"] is True


def test_s2_receipt_checks_pass():
    envelope = read_sample(SAMPLES / "S2_seoul_worker_bronchitis", "photo")
    bill = envelope["result"]["documents"][0]["kr_bill"]
    assert all_passed(check_kr_bill(bill))


def test_s3_total_rows_institution_and_code():
    envelope = read_sample(SAMPLES / "S3_us_tourist_hip_fracture", "photo")
    docs = envelope["result"]["documents"]
    assert [d["doc_type"] for d in docs] == ["receipt", "medical_certificate"]
    receipt = docs[0]
    assert receipt["currency"] == "KRW"
    assert receipt["total_amount"] == 15000000
    assert receipt["inpatient"] is True
    bill = receipt["kr_bill"]
    assert bill is not None
    assert bill["institution_type"] == "상급종합병원"
    assert bill["patient_type"] == "일반"
    assert bill["visit"] == "입원"
    assert bill["period_from"] == "2026-09-03"
    assert bill["period_to"] == "2026-09-09"
    assert len(bill["charge_rows"]) == 12
    assert [bill[f"cell_{n}"] for n in range(1, 11)] == [
        0,
        0,
        15000000,
        0,
        0,
        15000000,
        0,
        15000000,
        0,
        15000000,
    ]
    cert = docs[1]
    assert cert["diagnoses"][0]["code"] == "S72.120"
    assert cert["diagnoses"][0]["system"] == "KCD"
    assert cert["diagnoses"][0]["final"] is True


def test_s3_receipt_checks_pass():
    envelope = read_sample(SAMPLES / "S3_us_tourist_hip_fracture", "photo")
    bill = envelope["result"]["documents"][0]["kr_bill"]
    assert all_passed(check_kr_bill(bill))
