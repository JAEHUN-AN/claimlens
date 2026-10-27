"""Code conversion tests (SPEC 5.5). Deterministic, no model, no data files."""

import pytest

from claimlens.codes import (
    cm_candidates,
    convert_diagnosis,
    fracture_attribute,
    is_han_u_code,
    kcd_edition,
    normalize_kcd,
    pitfall_warning,
    who_from_kcd,
)


@pytest.mark.parametrize(
    ("kcd", "who", "attribute"),
    [
        ("A93.80", "A93.8", None),
        ("F32.21", "F32.2", None),
        ("S72.080", "S72.0", "closed"),
        ("S72.120", "S72.1", "closed"),
        ("M54.5", "M54.5", None),
    ],
)
def test_verified_who_examples(kcd, who, attribute):
    got, _ = who_from_kcd(kcd)
    assert got == who
    assert fracture_attribute(kcd) == attribute


def test_normalize_inserts_dot_and_rejects_garbage():
    assert normalize_kcd("S72120") == "S72.120"
    assert normalize_kcd(" s62.0 ") == "S62.0"
    with pytest.raises(ValueError):
        normalize_kcd("not a code")


def test_edition_follows_service_date():
    assert kcd_edition("2026-09-03") == "KCD-9"
    assert kcd_edition("2025-12-31") == "KCD-8"


def test_han_u_codes_do_not_convert():
    assert is_han_u_code("U22.0") is True
    assert is_han_u_code("S72.120") is False
    out = convert_diagnosis("U22.0")
    assert out["unconvertible"] is True
    assert out["who"] is None


def test_s3_cm_candidate_with_facts():
    out = cm_candidates("S72.1", {"laterality": "right", "open_closed": "closed"})
    assert out["chosen"] == "S72.141A"


def test_cm_defaults_and_narrowing_questions():
    out = cm_candidates("S72.1", {})
    assert out["chosen"] == "S72.143A"
    assert any("side" in q for q in out["questions"])
    assert any("Displaced" in q for q in out["questions"])


def test_cm_open_fracture_asks_gustilo_type():
    out = cm_candidates("S72.1", {"laterality": "left", "open_closed": "open"})
    assert out["chosen"] == "S72.142B"
    assert any("Gustilo" in q for q in out["questions"])


def test_cm_unknown_family_says_so():
    out = cm_candidates("J20.9", {})
    assert out["chosen"] is None
    assert "note" in out


def test_s3_pitfall_warning():
    warn = pitfall_warning("S72.120")
    assert warn is not None
    assert "lesser trochanter" in warn["warning"]
    assert pitfall_warning("S72.1") is None


def test_spine_pitfall_rows():
    assert "L3" in (pitfall_warning("S32.030") or {})["warning"]
    assert "L2" in (pitfall_warning("S32.020") or {})["warning"]


def test_hemorrhoid_exception_moves_to_bare_k64():
    got, notes = who_from_kcd("I84.1")
    assert got == "K64"
    assert "subdivision must be re-coded from the certificate" in notes
    bare, bare_notes = who_from_kcd("I84")
    assert bare == "K64"
    assert "subdivision must be re-coded from the certificate" not in bare_notes


def test_convert_diagnosis_end_to_end_for_s3():
    out = convert_diagnosis("S72.120", "2026-09-03", {"laterality": "right"})
    assert out["kcd"] == "S72.120"
    assert out["edition"] == "KCD-9"
    assert out["who"] == "S72.1"
    assert out["attribute"] == "closed"
    assert out["cm"]["chosen"] == "S72.141A"
    assert out["pitfall"] is not None
    assert "not an official mapping" in out["disclaimer"]
