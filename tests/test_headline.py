"""Headline: data-gated lines, README/demo regen, idempotence."""

import json
from pathlib import Path

from claimlens import headline
from claimlens.demo import REPO_ROOT, export_demo

ROOT = REPO_ROOT


def _fixture_hard(root: Path) -> None:
    real = json.loads((ROOT / "data" / "hard_eval_20261028.json").read_text(
        encoding="utf-8"))
    case = real["sets"]["hard"]["cases"][0]
    case = {**case, "runs": case["runs"][:2]}
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "hard_eval_20261028.json").write_text(
        json.dumps({"sets": {"hard": {"cases": [case]}}}, ensure_ascii=False),
        encoding="utf-8")


def test_gate_line_simulated_from_fixture(tmp_path):
    _fixture_hard(tmp_path)
    entry = headline.gate_line(tmp_path)
    assert "×2 runs" in entry["en"]
    assert "simulated from recorded runs" in entry["en"]
    assert "시뮬레이션" in entry["ko"]


def test_gate_line_live_drops_simulated(tmp_path):
    _fixture_hard(tmp_path)
    (tmp_path / "data" / "gate_live_20261028T000000Z.json").write_text(
        json.dumps({"repeat": 3, "sets": {"hard": {"pairs": 72, "stops": 40,
                                                  "leaks": 0}}}),
        encoding="utf-8")
    entry = headline.gate_line(tmp_path)
    assert "simulated" not in entry["en"]
    assert "live gate" in entry["en"]
    assert "40/72" in entry["en"]


def test_agent_and_load_lines(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    rows = [
        {"asked_when_needed": True, "no_needless": True, "no_invented": True},
        {"asked_when_needed": True, "no_needless": False, "no_invented": True},
    ]
    (tmp_path / "data" / "agent_eval.json").write_text(json.dumps({"rows": rows}),
                                                       encoding="utf-8")
    (tmp_path / "data" / "load_20261028T000000Z.json").write_text(
        json.dumps({"p50_s": 12.5, "p95_s": 20.0, "mean_cost_usd": 0.0123,
                    "runs": 5}), encoding="utf-8")
    agent = headline.agent_line(tmp_path)
    assert agent["en"].startswith("Agent scorecard: 1/2")
    load = headline.load_line(tmp_path)
    assert load["en"] == "Per claim: p50 12.5 s, p95 20 s, $0.0123 (5 concurrent live runs)"
    assert headline.after_n(tmp_path) == "12.5"


def test_missing_data_omits_lines(tmp_path):
    (tmp_path / "data").mkdir(exist_ok=True)
    assert headline.gate_line(tmp_path) is None
    assert headline.agent_line(tmp_path) is None
    assert headline.load_line(tmp_path) is None
    assert headline.after_n(tmp_path) is None
    assert len(headline.lines(tmp_path)) == 1


def test_real_lines_are_pinned():
    entries = headline.lines(ROOT)
    assert entries[0]["en"] == (
        "Hard documents ×3 runs: 47 wrong numbers left single read, 2 with the "
        "double-read gate (38/72 pairs stopped, live gate); clean documents: 2 left, "
        "1/30 stopped")
    assert entries[1]["en"].startswith("Agent scorecard: 8/8")
    assert entries[2]["en"] == "15 fault cases injected, no wrong number"
    assert entries[3]["en"] == (
        "Per claim: p50 22.97 s, p95 30.32 s, $0.0355 (5 concurrent live runs)")
    assert len(entries) == 4


def test_eval_caption_pinned():
    assert headline.eval_caption(ROOT) == (
        "Single read let 47 wrong numbers leave; the double-read gate leaves 2 "
        "(live gate).")


def test_apply_readme_inserts_and_idempotent(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(
        "ClaimLens works on the paperwork step. Bill photo → checked claim, "
        "every number traceable.\nTheme: Build for Your World.\n", encoding="utf-8")
    assert headline.apply_readme(readme, ROOT) is True
    text = readme.read_text(encoding="utf-8")
    assert "<!-- measured:start -->" in text
    assert "Agent scorecard: 8/8" in text
    assert headline.apply_readme(readme, ROOT) is False


def test_apply_readme_swaps_after_n(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "load_20261028T000000Z.json").write_text(
        json.dumps({"p50_s": 12.5, "p95_s": 20.0, "mean_cost_usd": 0.0123,
                    "runs": 5}), encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(
        "ClaimLens works on the paperwork step. Bill photo → checked claim, "
        "every number traceable.\nTheme: Build for Your World.\n", encoding="utf-8")
    assert headline.apply_readme(readme, tmp_path) is True
    assert "checked claim in about 12.5 s" in readme.read_text(encoding="utf-8")
    assert headline.apply_readme(readme, tmp_path) is False


def test_regen_is_idempotent_on_real_tree():
    assert headline.regen(ROOT) == {"readme": False, "model_table": False,
                                    "storyboard": False, "cards": False,
                                    "demo": False}


def test_demo_carries_measured_payload(tmp_path):
    dst = export_demo(tmp_path / "demo.html")
    text = dst.read_text(encoding="utf-8")
    assert "Hard documents ×3 runs: 47 wrong numbers left single read" in text
    assert "어려운 서류 ×3회" in text
    assert '"after_n": "22.97"' in text
    assert "why_after_n" in text
