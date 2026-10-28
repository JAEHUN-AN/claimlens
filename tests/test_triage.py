"""Messy bundle triage (stub provider, no network).

Bundle from existing sample images: shuffled S2 pages + a duplicate
receipt + one other-claim page.
"""

from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from claimlens.triage import render_report, triage_bundle, triage_pages

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
S2 = SAMPLES / "S2_seoul_worker_bronchitis"
A = SAMPLES / "A_niseko_wrist"

BUNDLE = [
    S2 / "medical_certificate_photo.jpg",
    S2 / "receipt_photo.jpg",
    A / "receipt_photo.jpg",
    S2 / "receipt_photo.jpg",
]

CLASSES = [
    {
        "kind": "medical_certificate",
        "patient": "NGUYEN VAN AN",
        "service_date": "2026-10-02",
        "total": None,
        "reason": "Medical certificate for NGUYEN VAN AN.",
    },
    {
        "kind": "receipt",
        "patient": "NGUYEN VAN AN",
        "service_date": "2026-10-02",
        "total": "KRW 45,000",
        "reason": "Hospital receipt.",
    },
    {
        "kind": "receipt",
        "patient": "TANAKA HANAKO",
        "service_date": "2026-01-15",
        "total": "JPY 235,000",
        "reason": "Hospital receipt.",
    },
    {
        "kind": "receipt",
        "patient": "NGUYEN VAN AN",
        "service_date": "2026-10-02",
        "total": "KRW 45,000",
        "reason": "Hospital receipt.",
    },
]


class _StubProvider:
    name = "stub"

    def __init__(self, pages: list[dict[str, Any]]):
        self._pages = pages
        self.calls: list[list[Path]] = []

    def read_documents(self, images, instructions, schema, result_model=None):
        self.calls.append(list(images))
        validated = TypeAdapter(result_model).validate_python({"pages": self._pages})
        return validated.model_dump(mode="json")


def test_messy_bundle_keeps_merges_drops_and_names_missing():
    assert all(p.is_file() for p in BUNDLE)
    provider = _StubProvider(CLASSES)
    result = triage_bundle(BUNDLE, provider)
    assert len(provider.calls) == 1 and len(provider.calls[0]) == 4
    assert result["kept"] == [{"index": 0, "kind": "medical_certificate"}, {"index": 1, "kind": "receipt"}]
    assert result["merged"] == [{"kept_index": 1, "from_index": 3}]
    assert len(result["dropped"]) == 1
    assert result["dropped"][0]["index"] == 2
    assert "TANAKA HANAKO" in result["dropped"][0]["reason"]
    assert result["missing"] == ["itemized statement missing"]
    assert result["claim"] == {"patient": "nguyen van an", "service_date": "2026-10-02"}
    assert [p["file"] for p in result["pages"]] == [p.name for p in BUNDLE]
    report = render_report(result)
    assert "merged [3] into [1] (duplicate)" in report
    assert "missing: itemized statement missing" in report


def test_unrelated_kind_dropped_with_reason():
    classes = [
        {"kind": "receipt", "patient": "A", "service_date": "d", "total": "t", "reason": "r"},
        {"kind": "unrelated", "patient": None, "service_date": None, "total": None, "reason": "A bus ticket."},
    ]
    result = triage_pages(classes)
    assert result["kept"] == [{"index": 0, "kind": "receipt"}]
    assert result["dropped"] == [{"index": 1, "reason": "unrelated: A bus ticket."}]


def test_identity_tie_keeps_first_page():
    classes = [
        {"kind": "receipt", "patient": "A", "service_date": "d", "total": "t", "reason": "r"},
        {"kind": "receipt", "patient": "B", "service_date": "e", "total": "t", "reason": "r"},
    ]
    result = triage_pages(classes)
    assert result["kept"] == [{"index": 0, "kind": "receipt"}]
    assert result["dropped"][0]["index"] == 1


def test_length_mismatch_raises():
    provider = _StubProvider(CLASSES[:2])
    try:
        triage_bundle(BUNDLE, provider)
    except ValueError as exc:
        assert "2 entries for 4 images" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_cli_triage_reports(monkeypatch, capsys):
    import claimlens.rationale as rationale_mod
    from claimlens.cli import build_parser

    monkeypatch.setattr(
        rationale_mod, "rationale_provider_default", lambda: _StubProvider(CLASSES)
    )
    args = build_parser().parse_args(["triage", *(str(p) for p in BUNDLE)])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "missing: itemized statement missing" in out
    assert "dropped [2]" in out
