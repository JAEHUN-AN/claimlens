"""Live gate eval: plan-only default, stub pairs, abort, temp isolation."""

import copy
import json
import subprocess
from pathlib import Path

from claimlens import gate_eval
from claimlens.cli import main
from claimlens.engine import replay_reading
from claimlens.eval import ground_truth, load_scenarios
from claimlens.hard_eval import BASE_EST, REREAD_EST
from claimlens.providers.meta import CallRecord
from claimlens.reader import resolve_sample_images

ROOT = Path(__file__).resolve().parent.parent


def test_gate_plan_prints_and_stops(capsys, tmp_path):
    assert main(["gate-eval", "--output", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "normal: 10 cases x3" in out
    assert "hard: 24 cases x3" in out
    assert "Stopped before any API call" in out
    assert f"${204 * BASE_EST:.2f}" in out
    assert list(tmp_path.iterdir()) == []


def test_gate_plan_estimate_math():
    text = gate_eval.estimate_text("hard", 24, 16, 3)
    assert "72 pairs" in text
    assert "144 reads + up to 96 re-reads" in text
    assert f"${144 * BASE_EST:.2f}" in text
    assert f"${144 * BASE_EST + 96 * REREAD_EST:.2f}" in text


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
    assert summary["stops"] == 1
    assert summary["leaks"] == 1
    assert summary["spent"] == 0.06
    assert summary["per_claim"] == 0.02
    assert results["aborted"] is False
    tags = [tag for stub in stubs for tag in stub.tags]
    assert len(set(tags)) == 6
    assert all(tag.startswith(".gate41c-r1") for tag in tags)
    files = list(tmp_path.glob("gate_live_*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8"))["sets"]["normal"]["leaks"] == 1


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
