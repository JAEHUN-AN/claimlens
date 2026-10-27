"""Eval table tests: ground truth and cached-sample comparison, no live calls."""

from claimlens.eval import compare, eval_sample, format_markdown, ground_truth, load_scenarios


def test_ground_truth_covers_all_samples():
    scenarios = load_scenarios()
    assert set(scenarios) >= {
        "A_niseko_wrist",
        "B_chiangmai_dogbite",
        "C_newyork_panic",
        "S2_seoul_worker_bronchitis",
        "S3_us_tourist_hip_fracture",
    }
    truth = ground_truth(scenarios["A_niseko_wrist"])
    assert truth["currency"] == "JPY"
    assert truth["total"] == 235000
    assert truth["line_count"] == 6
    truth_s3 = ground_truth(scenarios["S3_us_tourist_hip_fracture"])
    assert truth_s3["total"] == 15000000
    assert truth_s3["line_count"] == 12
    assert truth_s3["kr_cells"] is not None
    assert len(truth_s3["kr_cells"] or []) == 10


def test_eval_cached_a_photo_passes():
    row = eval_sample("A_niseko_wrist", "photo")
    assert row.get("error") is None
    assert row["docs"] == "ok"
    assert row["currency"] == "ok"
    assert row["total"] == "ok"
    assert row["lines"] == "6/6"
    assert row["amounts"] == "ok"
    assert row["diags"] == "1/1"
    assert row["pii"] == "4/4"
    assert row["calls"] == 1
    assert row["tokens"] > 0


def test_eval_cached_s3_photo_passes():
    row = eval_sample("S3_us_tourist_hip_fracture", "photo")
    assert row.get("error") is None
    assert row["total"] == "ok"
    assert row["lines"] == "12/12"
    assert row["kr_cells"] == "10/10"
    assert row["instit"] == "ok"
    assert row["checks"] == "pass"
    assert row["diags"] == "1/1"


def test_compare_detects_mismatch():
    scenarios = load_scenarios()
    truth = ground_truth(scenarios["A_niseko_wrist"])
    reading = {"documents": [{"doc_type": "receipt", "currency": "USD"}]}
    out = compare("A_niseko_wrist", truth, reading)
    assert out["currency"] == "FAIL"
    assert out["total"] == "FAIL"


def test_format_markdown_table():
    rows = [
        {
            "sample": "A_niseko_wrist",
            "variant": "photo",
            "docs": "ok",
            "currency": "ok",
            "total": "ok",
            "lines": "6/6",
            "amounts": "ok",
            "diags": "1/1",
            "kr_cells": "n/a",
            "instit": "n/a",
            "checks": "n/a",
            "pii": "4/4",
            "calls": 1,
            "tokens": 100,
            "cost": None,
        }
    ]
    text = format_markdown(rows)
    assert text.startswith("| sample | variant |")
    assert "A_niseko_wrist" in text
    assert text.count("\n") == 3


def test_eval_cost_uses_configured_rates(monkeypatch):
    monkeypatch.setenv("CLAIMLENS_USD_PER_1K_INPUT", "0.00125")
    monkeypatch.setenv("CLAIMLENS_USD_PER_1K_OUTPUT", "0.00425")
    row = eval_sample("A_niseko_wrist", "photo")
    assert row.get("error") is None
    assert row["cost"] is not None and row["cost"] > 0
    assert "$" in format_markdown([row])


def test_eval_output_flag_writes_file(tmp_path, capsys):
    from claimlens.cli import main

    target = tmp_path / "eval.md"
    assert main(["eval", "--output", str(target)]) == 0
    body = target.read_text(encoding="utf-8")
    assert body.startswith("# ClaimLens reading accuracy")
    assert "A_niseko_wrist" in body
    assert "S3_us_tourist_hip_fracture" in body
    out = capsys.readouterr().out
    assert "| sample | variant |" in out
