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


def test_gate_line_live_opens_with_conclusion(tmp_path):
    _fixture_hard(tmp_path)
    (tmp_path / "data" / "gate_live_20261028T000000Z.json").write_text(
        json.dumps({"repeat": 3, "sets": {"hard": {"pairs": 72, "stops": 40,
                                                  "leaks": 0}}}),
        encoding="utf-8")
    entry = headline.gate_line(tmp_path)
    assert "simulated" not in entry["en"]
    assert entry["en"].startswith("Live double-read gate")
    assert "0 wrong amounts left" in entry["en"]
    assert "40 stopped for a person" in entry["en"]
    assert "current pipeline" in entry["en"]
    assert "old pipeline" not in entry["en"]  # legacy_line holds it now
    assert "Fields scored" not in entry["en"]  # footnote holds it now
    assert "normal documents" not in entry["en"]  # fixture has no normal set
    legacy = headline.legacy_line(tmp_path)
    assert legacy["en"].startswith("Single read, 2026-10-28 run on the old pipeline")
    footnote = headline.scope_footnote(tmp_path)
    assert footnote["en"] == (
        "Fields scored: total, line amounts, Korean bill cells.")


def test_measured_block_opens_with_conclusion_and_footnote(tmp_path):
    _fixture_hard(tmp_path)
    (tmp_path / "data" / "gate_live_20261028T000000Z.json").write_text(
        json.dumps({"repeat": 3, "sets": {"hard": {"pairs": 72, "stops": 40,
                                                  "leaks": 0}}}),
        encoding="utf-8")
    entries = headline.lines(tmp_path)
    assert entries[0]["en"].startswith("Live double-read gate")
    assert entries[1]["en"].startswith("Single read, 2026-10-28")
    footnote = headline.scope_footnote(tmp_path)
    block = headline.render_readme_block(entries, footnote)
    assert block.splitlines()[2].startswith("- Live double-read gate")
    assert block.splitlines()[-2] == footnote["en"]
    assert block.splitlines()[-1] == "<!-- measured:end -->"

def _gate_file_with_details(old: dict) -> dict:
    new = json.loads(json.dumps(old))
    for summary in new["sets"].values():
        summary["pair_details"] = [
            {"round": 1,
             "case": {"sample": "A_niseko_wrist", "variant": "photo"},
             "tags": [".gate41c-r1a-x", ".gate41c-r1b-x"],
             "agree": True, "stopped": False, "stopped_each": [False, False],
             "reached": 0, "wrong_fields": [],
             "values": [{"total": 235000}, {"total": 235000}], "calls": []},
        ]
    return new


def test_gate_line_reads_old_and_new_format(tmp_path):
    old = json.loads((ROOT / "data" / "gate_live_20261028T212938Z.json").read_text(
        encoding="utf-8"))
    roots = []
    for name, payload in (("old", old), ("new", _gate_file_with_details(old))):
        root = tmp_path / name
        _fixture_hard(root)
        (root / "data" / "gate_live_20261028T212938Z.json").write_text(
            json.dumps(payload), encoding="utf-8")
        roots.append(root)
    assert headline.gate_line(roots[0]) == headline.gate_line(roots[1])
    assert headline.legacy_line(roots[0]) == headline.legacy_line(roots[1])
    assert headline.scope_footnote(roots[0]) == headline.scope_footnote(roots[1])
    assert headline.eval_caption(roots[0]) == headline.eval_caption(roots[1])
    assert "Live double-read gate" in headline.gate_line(roots[1])["en"]


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
    assert headline.legacy_line(tmp_path) is None
    assert headline.scope_footnote(tmp_path) is None
    assert headline.trips_line(tmp_path) is None
    assert headline.agent_line(tmp_path) is None
    assert headline.load_line(tmp_path) is None
    assert headline.after_n(tmp_path) is None
    assert len(headline.lines(tmp_path)) == 1


def test_real_lines_are_pinned():
    entries = headline.lines(ROOT)
    assert entries[0]["en"] == (
        "Live double-read gate, 2026-10-31 run on the current pipeline "
        "(24 cases ×3 = 72 pairs): 0 wrong amounts left (34 stopped for a "
        "person); normal documents: 0 left, 2/30 stopped.")
    assert entries[1]["en"] == (
        "Single read, 2026-10-28 run on the old pipeline (before the line-sum "
        "check and rotation probe): 47 wrong amounts left (hard set, 23/24 "
        "cases ×3).")
    assert entries[2]["en"] == (
        "Unseen layouts + real trips, first run before fixes (2026-10-29): 0 wrong "
        "amounts left over 84 pairs (30 stopped for a person); after fixes "
        "(2026-10-31, wider scoring): 0 wrong values left over 84 pairs (9 stopped).")
    assert entries[3]["en"] == (
        "Real trips through live upload, 2026-10-31 run: 3 of 6 decided "
        "(T1, T2, T3); each paid amount matches the truth KRW total; "
        "T4 (needs_manual_check), T6 (needs_review) correctly not decided; "
        "T5 stopped for a person.")
    assert entries[4]["en"] == (
        "Agent scorecard: 8/8 (7 agent dialogues + 1 voice rule, each replayed "
        "once from its recording)")
    assert entries[5]["en"] == (
        "15 fault cases injected in tests (no live calls), no wrong number")
    assert entries[6]["en"] == (
        "Per claim (S2 retake photos, 5 concurrent live runs): p50 22.97 s, "
        "p95 30.32 s, $0.0355; outcomes PARTIAL 3, needs_manual_check 2 "
        "(PARTIAL = partly paid, needs_manual_check = stopped for a person); "
        "median run needs_manual_check")
    assert len(entries) == 7
    footnote = headline.scope_footnote(ROOT)
    assert footnote["en"] == (
        "Fields scored in the current runs: total, line amounts, Korean bill cells, "
        "currency, country, service date, inpatient stay, diagnosis codes, charge rows. "
        "Older runs (the single-read line and the first run before fixes) scored "
        "total, line amounts, Korean bill cells only.")

def test_scope_labels_track_gate_fields():
    from claimlens.hard_eval import GATE_FIELDS

    assert set(headline.SCOPE_LABELS) == set(GATE_FIELDS)
    assert set(headline.SCOPE_LABELS_KO) == set(GATE_FIELDS)


def _fixture_trips(root: Path) -> None:
    truth = {"cases": [
        {"id": "T1_x", "totals": {"krw": 1000},
         "expected": {"serve_today": {"status": 200, "badge": "engine_unreachable"},
                      "serve_engine_up": {"status": 200, "badges": ["PAID"]}}},
        {"id": "T2_y", "totals": {"krw": 2000},
         "expected": {"serve_today": {"status": 200, "badge": "engine_unreachable"},
                      "serve_engine_up": {"status": 200, "badges": ["PAID"]}}},
        {"id": "T4_z", "totals": {"krw": 50},
         "expected": {"serve_today": {"status": 200, "badge": "needs_manual_check"},
                      "serve_engine_up": {"status": 200, "badges": []}}},
        {"id": "T5_w", "totals": {"krw": 0},
         "expected": {"serve_today": {"status": 200, "badge": "engine_unreachable"},
                      "serve_engine_up": {"status": 200, "badges": ["PAID"]}}},
        {"id": "T6_v", "totals": {"krw": 0},
         "expected": {"serve_today": {"status": 200, "badge": "PAID"},
                      "serve_engine_up": {"status": 200, "badges": []}}},
    ]}
    tdir = root / "samples" / "unseen" / "trips"
    tdir.mkdir(parents=True)
    (tdir / "truth.json").write_text(json.dumps(truth), encoding="utf-8")
    run = {"cases": [
        {"case": "T1_x", "badge": "PAID", "title": "1,000 KRW"},
        {"case": "T2_y", "badge": "PAID", "title": "9,999 KRW"},
        {"case": "T4_z", "badge": "needs_manual_check",
         "title": "Human review: no certificate."},
        {"case": "T5_w", "badge": "engine_unreachable", "title": ""},
        {"case": "T6_v", "badge": "weird_badge", "title": ""},
    ]}
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "trips_check_20261030T000000Z.json").write_text(
        json.dumps(run), encoding="utf-8")


def test_trips_line_buckets_come_from_data(tmp_path):
    _fixture_trips(tmp_path)
    entry = headline.trips_line(tmp_path)
    assert entry["en"] == (
        "Real trips through live upload, 2026-10-30 run: 2 of 5 decided "
        "(T1, T2); T2 paid 9,999 KRW, truth 2,000 KRW; "
        "T4 (needs_manual_check) correctly not decided; "
        "T5 paused as expected with the engine down; "
        "T6 (weird_badge) not decided.")
    assert "5건 중 2건 판정" in entry["ko"]
    assert "의도대로 미판정" in entry["ko"]


def test_trips_line_omitted_without_data(tmp_path):
    (tmp_path / "data").mkdir(exist_ok=True)
    assert headline.trips_line(tmp_path) is None


def test_heldout_line_omitted_without_data(tmp_path):
    (tmp_path / "data").mkdir(exist_ok=True)
    assert headline.heldout_line(tmp_path) is None


def test_after_sentence_drops_scope_paren():
    assert headline.after_sentence(ROOT) == (
        "Bill photo → checked claim in about 22.97 s, every number traceable.")
    assert "(" not in headline.after_sentence(ROOT)

def test_eval_caption_pinned():
    caption = headline.eval_caption(ROOT)
    assert caption == (
        "Single read (2026-10-28, old pipeline) let 47 wrong amounts leave; "
        "the live gate (2026-10-31, current pipeline) leaves 0.")
    assert len(caption) <= 190


def test_apply_readme_inserts_and_idempotent(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(
        "ClaimLens works on the paperwork step. Bill photo → checked claim, "
        "every number traceable.\nTheme: Build for Your World.\n", encoding="utf-8")
    assert headline.apply_readme(readme, ROOT) is True
    text = readme.read_text(encoding="utf-8")
    assert "<!-- measured:start -->" in text
    assert "Agent scorecard: 8/8" in text
    assert "Fields scored in the current runs: total, line amounts" in text
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
                                    "demo": False, "figure": False}


def test_demo_carries_measured_payload(tmp_path):
    dst = export_demo(tmp_path / "demo.html")
    text = dst.read_text(encoding="utf-8")
    assert "Single read, 2026-10-28 run on the old pipeline" in text
    assert "단일 판독, 2026-10-28 구 파이프라인 실행" in text
    assert "Unseen layouts + real trips, first run before fixes (2026-10-29)" in text
    assert '"after_n": "22.97"' in text
    assert '"measured_footnote"' in text
    assert "after_scope" not in text
    assert "why_after_n" in text


def test_scope_comes_from_the_run_not_the_current_code():
    # Runs recorded before C1 scored amounts only; the label must not claim more.
    assert headline._scope_text({})[0] == "total, line amounts, Korean bill cells"
    assert headline._scope_text({"fields": ["total", "currency"]})[0] == "total, currency"
