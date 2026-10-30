"""Live gate eval: plan-only default, stub pairs, abort, temp isolation."""

import copy
import json
import subprocess
from pathlib import Path

from claimlens import gate_eval
from claimlens.cli import main
from claimlens.engine import replay_reading
from claimlens.eval import ground_truth, load_scenarios
from claimlens.hard_eval import BASE_EST, PROBE_EST, REREAD_EST
from claimlens.providers.meta import CallRecord
from claimlens.reader import resolve_sample_images

ROOT = Path(__file__).resolve().parent.parent


def test_eval_md_gate_runs_table_matches_data():
    """53-H3: every committed normal+hard gate run is in docs/eval.md, exact."""
    text = (ROOT / "docs" / "eval.md").read_text(encoding="utf-8")
    files = sorted((ROOT / "data").glob("gate_live_*.json"))
    hard_runs = [p for p in files
                 if "hard" in json.loads(p.read_text(encoding="utf-8"))["sets"]]
    assert len(hard_runs) == 4
    for path in hard_runs:
        data = json.loads(path.read_text(encoding="utf-8"))
        for name in ("normal", "hard"):
            entry = data["sets"][name]
            row = f"{entry['pairs']} / {entry['stops']} / {entry['leaks']}"
            assert row in text, (path.name, name)
        assert f"${data['spent']:.2f}" in text
        assert path.name in text
    assert "same document families" in text
    assert "`data/gate_live_20261029T070828Z.json`" in text


def test_gate_plan_prints_and_stops(capsys, tmp_path):
    assert main(["gate-eval", "--output", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "normal: 10 cases x3" in out
    assert "hard: 24 cases x3" in out
    assert "Stopped before any API call" in out
    assert "144 rotation probes" in out  # hard pairs probe both pages
    assert "60 rotation probes" in out  # clean pages too: false turns are measured
    assert f"${204 * BASE_EST + 204 * PROBE_EST:.2f}" in out
    assert list(tmp_path.iterdir()) == []


def test_gate_plan_estimate_math():
    text = gate_eval.estimate_text("hard", 24, 3)
    assert "72 pairs" in text
    assert "144 reads + up to 144 verify re-reads" in text
    assert f"${144 * BASE_EST:.2f}" in text
    hi = 144 * BASE_EST + 144 * REREAD_EST
    assert f"${hi:.2f}" in text


class _GateStub:
    def __init__(self, script):
        self._script = script
        self.calls = []
        self.tags = []

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self.tags.append(cache_tag)
        self.calls.append(CallRecord(model="stub", input_tokens=100, output_tokens=0,
                                     total_tokens=100, cost_usd=0.01))
        if result_model is not None:
            return {}
        return copy.deepcopy(self._script.pop(0))


def _case(sample, readings):
    scenarios = load_scenarios()
    truth = ground_truth(scenarios[sample])
    images = resolve_sample_images(ROOT / "samples" / sample, "photo")
    return {"sample": sample, "variant": "photo", "key": f"{sample}-photo",
            "images": images, "truth": truth,
            "unreadable": {"total": False, "line_amounts": False, "kr_cells": []}}


def _a_reading(total=None):
    reading = replay_reading("A_niseko_wrist", "photo")
    if total is not None:
        reading["documents"][0]["total_amount"] = total
    return reading


def _factory(script, stubs):
    def make():
        stub = _GateStub(script)
        stubs.append(stub)
        return stub

    return make


def test_execute_stub_pairs(tmp_path):
    good = _a_reading()
    bad = _a_reading(total=999999)
    cases = [_case("A_niseko_wrist", None) for _ in range(3)]
    for pos, case in enumerate(cases):
        case["key"] = f"A_niseko_wrist-photo-{pos}"
    script = [good, good, bad, bad, good, bad]
    stubs = []
    results = gate_eval.execute({"normal": {"cases": cases}}, 1, 4.00,
                                _factory(script, stubs), tmp_path)
    summary = results["sets"]["normal"]
    assert summary["pairs"] == 3
    assert summary["stops"] == 2
    assert summary["leaks"] == 0
    assert summary["spent"] == 0.09
    assert summary["per_claim"] == 0.03
    assert results["aborted"] is False
    tags = [tag for stub in stubs for tag in stub.tags if tag]
    assert len(set(tags)) == 6
    assert all(tag.startswith(".gate41c-r1") for tag in tags)
    files = list(tmp_path.glob("gate_live_*.json"))
    assert len(files) == 1
    stored = json.loads(files[0].read_text(encoding="utf-8"))["sets"]["normal"]
    assert stored["leaks"] == 0
    details = stored["pair_details"]
    assert len(details) == 3
    assert [d["reached"] for d in details] == [0, 0, 0]
    assert details[1]["wrong_fields"] == []
    assert details[1]["case"] == {"sample": "A_niseko_wrist", "variant": "photo"}
    assert [v["total"] for v in details[1]["values"]] == [999999, 999999]
    assert sum(d["reached"] for d in details) == stored["leaks"]
    assert sum(d["stopped"] for d in details) == stored["stops"]


def test_execute_aborts_past_max_cost(tmp_path):
    good = _a_reading()
    cases = [_case("A_niseko_wrist", None) for _ in range(3)]
    for pos, case in enumerate(cases):
        case["key"] = f"A_niseko_wrist-photo-{pos}"
    script = [good] * 6
    results = gate_eval.execute({"normal": {"cases": cases}}, 1, 0.03,
                                _factory(script, []), tmp_path)
    assert results["aborted"] is True
    assert results["sets"]["normal"]["pairs"] < 3
    assert list(tmp_path.glob("gate_live_*.json")) != []


def test_execute_leaves_committed_cache_clean(tmp_path):
    good = _a_reading()
    case = _case("A_niseko_wrist", None)
    gate_eval.execute({"normal": {"cases": [case]}}, 1, 4.00,
                      _factory([good, good], []), tmp_path)
    assert list((ROOT / "cache").glob("*.gate41c*")) == []
    assert list((ROOT / "cache" / "live").glob("*.gate41c*")) == []
    proc = subprocess.run(["git", "-c", "safe.directory=C:/hack/claimlens",
                           "status", "--porcelain", "cache/"],
                          check=False, capture_output=True, text=True, cwd=ROOT)
    assert proc.stdout.strip() == ""


def test_run_pair_disagree_never_passes():
    good = _a_reading()
    bad = _a_reading(total=999999)
    case = _case("A_niseko_wrist", None)
    record = gate_eval.run_pair(case, 2, _factory([good, bad], []))
    assert record["agree"] is False
    assert record["stopped"] is True
    assert record["reached"] == 0
    assert record["tags"] == [".gate41c-r2a-A_niseko_wrist-photo",
                              ".gate41c-r2b-A_niseko_wrist-photo"]


def test_run_pair_total_check_stops_agreeing_wrong_total():
    bad = _a_reading(total=999999)
    case = _case("A_niseko_wrist", None)
    record = gate_eval.run_pair(case, 1, _factory([bad, bad], []))
    assert record["agree"] is True
    assert record["case"] == {"sample": "A_niseko_wrist", "variant": "photo"}
    assert [v["total"] for v in record["values"]] == [999999, 999999]
    assert record["wrong_fields"] == []
    assert record["stopped_each"] == [True, True]
    assert record["stopped"] is True
    assert record["reached"] == 0


def test_run_pair_clean_agree_saves_empty_wrong_fields():
    good = _a_reading()
    case = _case("A_niseko_wrist", None)
    record = gate_eval.run_pair(case, 1, _factory([good, good], []))
    assert record["agree"] is True
    assert record["stopped"] is False
    assert record["wrong_fields"] == []
    assert len(record["values"]) == 2


def test_agreeing_pair_stops_when_either_read_failed_verify(monkeypatch):
    # serve stops when any read fails its verify; the harness must count the same way.
    good = _a_reading()
    outcomes = iter([False, True])  # read 1 passes verify, read 2 does not

    def fake_verify(reading, image, provider, calls):
        return reading, next(outcomes)

    monkeypatch.setattr(gate_eval, "_verify_final", fake_verify)
    record = gate_eval.run_pair(_case("A_niseko_wrist", None), 1,
                                _factory([good, good], []))
    assert record["agree"] is True
    assert record["stopped"] is True
    assert record["reached"] == 0
