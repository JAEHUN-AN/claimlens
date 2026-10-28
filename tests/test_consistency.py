"""Cross-document consistency: deterministic pins plus Spark verification."""

from typing import Any

import pytest

from claimlens.consistency import (
    BUNDLES,
    bundle_reading,
    check_consistency,
    deterministic_findings,
    eval_all,
    quotes_found,
    score_bundle,
    spark_findings,
)
from claimlens.providers.replay import ReplayProvider


class StubProvider:
    name = "stub"
    model = "stub"

    def __init__(self, findings: list[dict[str, Any]]):
        self.findings = findings
        self.calls: list[Any] = []

    def write(self, instructions: str, schema: dict[str, Any], result_model: Any = None):
        assert "character-for-character" in instructions
        assert "fraud" in instructions
        return {"findings": self.findings}


def _blocker_kinds(bundle_id: str) -> list[str]:
    docs = bundle_reading(bundle_id)
    ruled = deterministic_findings(docs["receipt"], docs["cert"])
    return sorted(f["kind"] for f in ruled if f["severity"] == "blocker")


@pytest.mark.parametrize("bundle_id", ["A", "S2", "S3"])
def test_matched_bundles_have_no_blockers(bundle_id):
    assert _blocker_kinds(bundle_id) == []


@pytest.mark.parametrize(
    "bundle_id",
    ["S2r-S3c", "Ar-Cc", "S2r-Ac"],
)
def test_mismatched_bundles_match_expected_kinds(bundle_id):
    assert _blocker_kinds(bundle_id) == sorted(BUNDLES[bundle_id]["expected"])


def test_hospital_mismatch_is_a_note_not_a_blocker():
    docs = bundle_reading("Ar-Cc")
    ruled = deterministic_findings(docs["receipt"], docs["cert"])
    hospital = [f for f in ruled if f["kind"] == "hospital"]
    assert len(hospital) == 1
    assert hospital[0]["severity"] == "check"
    assert "question" not in hospital[0]


def test_blockers_carry_ask_user_payloads():
    docs = bundle_reading("S2r-S3c")
    ruled = deterministic_findings(docs["receipt"], docs["cert"])
    blockers = [f for f in ruled if f["severity"] == "blocker"]
    assert len(blockers) == 3
    for finding in blockers:
        assert finding["question"] and finding["why_needed"]


def test_quotes_must_occur_in_their_reading():
    docs = bundle_reading("S2r-S3c")
    receipt, cert = docs["receipt"], docs["cert"]
    assert quotes_found(
        {"quote_receipt": "NGUYEN VAN AN", "quote_cert": "Michael J. CARTER"},
        receipt,
        cert,
    )
    assert not quotes_found(
        {"quote_receipt": "nobody printed", "quote_cert": "Michael J. CARTER"},
        receipt,
        cert,
    )
    assert not quotes_found({"quote_receipt": "", "quote_cert": "x"}, receipt, cert)


def test_spark_layer_drops_invented_and_banned_findings():
    docs = bundle_reading("Ar-Cc")
    stub = StubProvider(
        [
            {
                "kind": "prose_date",
                "severity": "blocker",
                "quote_receipt": "2026-08-12",
                "quote_cert": "2026-08-20",
                "reason": "Printed dates differ across the documents.",
            },
            {
                "kind": "billed_not_described",
                "severity": "check",
                "quote_receipt": "surgery never billed",
                "quote_cert": "Jieun LEE",
                "reason": "Invented quote must go.",
            },
            {
                "kind": "other",
                "severity": "check",
                "quote_receipt": "Hana KIM",
                "quote_cert": "Jieun LEE",
                "reason": "Possible fraud here.",
            },
        ]
    )
    kept, dropped = spark_findings(docs["receipt"], docs["cert"], stub)
    assert [f["kind"] for f in kept] == ["prose_date"]
    assert kept[0]["layer"] == "spark"
    assert dropped == 2


def test_score_bundle_math():
    assert score_bundle("A", [])["precision"] == 1.0
    assert score_bundle("A", [])["recall"] == 1.0
    row = score_bundle("S2r-S3c", ["patient_name", "visit_date"])
    assert row["precision"] == 1.0
    assert row["recall"] == pytest.approx(2 / 3, abs=0.001)
    row = score_bundle("S2r-Ac", ["patient_name", "visit_date", "birth_date"])
    assert row["precision"] == pytest.approx(2 / 3, abs=0.001)


@pytest.mark.parametrize("bundle_id", sorted(BUNDLES))
def test_replay_pins_every_bundle(bundle_id):
    result = check_consistency(bundle_id, ReplayProvider())
    assert result["stopped"] == (bundle_id not in ("A", "S2", "S3"))
    ruled = [f["kind"] for f in result["findings"] if f["layer"] == "rule" and f["severity"] == "blocker"]
    assert sorted(ruled) == sorted(BUNDLES[bundle_id]["expected"])


def test_eval_replay_is_perfect_on_rule_kinds():
    rows = eval_all(ReplayProvider())
    assert [r["bundle"] for r in rows] == list(BUNDLES)
    assert all(r["precision"] == 1.0 and r["recall"] == 1.0 for r in rows)
