"""Eval table tests: ground truth and cached-sample comparison, no live calls."""

from pathlib import Path

from claimlens.eval import compare, eval_sample, format_markdown, ground_truth, load_scenarios

ROOT = Path(__file__).resolve().parent.parent


def test_eval_sample_has_open_columns():
    row = eval_sample("A_niseko_wrist", "photo")
    opened = row["open"]
    assert opened["total"] == "ok"
    assert opened["lines"] == "6/6"
    assert opened["checks"] == "pass"
    assert "reasoning" in opened["tokens"]
    assert opened["latency_ms"] > 0


def test_open_columns_pin_known_gaps():
    assert eval_sample("C_newyork_panic", "photo")["open"]["total"] == "FAIL"
    assert eval_sample("S3_us_tourist_hip_fracture", "clean")["open"]["lines"] == "12/12"
    assert eval_sample("S2_seoul_worker_bronchitis", "photo")["open"]["checks"] == "FAIL"


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


def _table_cells(text):
    """score cells per sample+variant from a Markdown eval table."""
    rows = {}
    for line in text.splitlines():
        if not line.startswith("| ") or line.startswith("| sample |"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 21:  # other tables in the file are narrower
            continue
        rows[(cells[0], cells[1])] = cells
    return rows


def test_committed_readme_tables_match_current_code():
    """53-H7: README Eval tables equal a fresh replay eval."""
    from claimlens.eval import eval_all, format_readme_tables

    committed = (ROOT / "README.md").read_text(encoding="utf-8")
    table1, table2 = format_readme_tables(eval_all())
    for table in (table1, table2):
        for row in table.strip().splitlines():
            assert row in committed, row


def test_committed_eval_table_matches_current_code():
    """53-H7: docs/eval.md accuracy cells equal a fresh replay eval."""
    from claimlens.eval import eval_all, format_markdown

    committed = (ROOT / "docs" / "eval.md").read_text(encoding="utf-8")
    fresh = format_markdown(eval_all())
    old, new = _table_cells(committed), _table_cells(fresh)
    assert len(old) == len(new) == 10
    picks = (4, 5, 6, 7, 8, 10, 11, 15, 16, 17)  # accuracy + open accuracy
    for key, fresh_cells in new.items():
        assert key in old, key
        for idx in picks:
            assert old[key][idx] == fresh_cells[idx], (key, idx)
