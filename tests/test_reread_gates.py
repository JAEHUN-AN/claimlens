"""41e(a) stub tests: receipt-total gates (no network)."""
import copy
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from claimlens.checks import all_passed, receipt_checks
from claimlens.providers.meta import CallRecord
from claimlens.verify import verify_receipt

ROOT = Path(__file__).resolve().parent.parent


def _stamp(path: Path, size=(20, 10)):
    Image.new("RGB", size, "white").save(path)
    return path


def _call():
    return CallRecord(model="stub", input_tokens=10, output_tokens=5,
                      total_tokens=15, cost_usd=None)


class _RereadStub:
    """verify_receipt stub: base reads fail, the narrow re-read is scripted."""

    name = "stub"

    def __init__(self, reread: dict):
        self._reread = reread
        self.calls = []
        self.seen: list[dict] = []

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self.calls.append(_call())
        self.seen.append({"images": list(images), "instructions": instructions,
                          "schema": schema, "result_model": result_model})
        return copy.deepcopy(self._reread)


def _c_like(total=0.0):
    return {
        "doc_type": "receipt", "currency": "USD", "country": "US",
        "total_amount": total,
        "line_items": [{"description": "ER facility fee", "amount": 3200.0,
                        "category": "consultation"}],
    }


def test_total_zero_fails_both_receipt_checks():
    checks = receipt_checks(_c_like())
    failed = sorted(c.name for c in checks if not c.passed)
    assert failed == ["lines_sum_total", "total_positive"]
    assert not all_passed(checks)


def test_receipt_total_edges():
    assert not all_passed(receipt_checks({"total_amount": None, "line_items": []}))
    missing_line = {"country": "US", "currency": "USD", "total_amount": 100.0,
                    "line_items": [{"amount": None}]}
    assert [c.name for c in receipt_checks(missing_line) if not c.passed] == [
        "lines_sum_total"]
    close = {"country": "US", "currency": "USD", "total_amount": 100.0,
             "line_items": [{"amount": 60.0}, {"amount": 40.0}]}
    assert all_passed(receipt_checks(close))


def test_narrow_reread_repairs_total(tmp_path):
    stub = _RereadStub({"total_amount": 3200.0})
    image = _stamp(tmp_path / "receipt.png")
    result = verify_receipt(_c_like(), image, stub)
    assert result["status"] == "verified"
    assert result["corrected"] == ["total_amount"]
    assert result["receipt"]["total_amount"] == 3200.0
    assert len(stub.calls) == 1
    only = stub.seen[0]
    assert "total_amount" in only["instructions"]
    assert "line_items" not in only["instructions"]
    assert list(only["schema"].get("properties", {})) == ["total_amount"]


def test_stubborn_total_stops_for_manual_check(tmp_path):
    stub = _RereadStub({"total_amount": 0.0})
    result = verify_receipt(_c_like(), _stamp(tmp_path / "r.png"), stub)
    assert result["status"] == "needs_manual_check"
    assert result["corrected"] == []
    assert sorted(result["failing"]) == ["lines_sum_total", "total_positive"]
    assert len(stub.calls) == 1


def _gate_case(tmp_path):
    from claimlens.engine import load_scenarios
    from claimlens.eval import ground_truth

    scenarios, _ = load_scenarios()
    return {
        "key": "A_niseko_wrist-photo",
        "sample": "A_niseko_wrist", "variant": "photo",
        "images": [_stamp(tmp_path / "receipt.png"),
                   _stamp(tmp_path / "cert.png")],
        "truth": ground_truth(scenarios["A_niseko_wrist"]),
        "unreadable": {"total": False, "line_amounts": False, "kr_cells": []},
    }


class _GateStub:
    name = "stub"

    def __init__(self, readings):
        self._readings = list(readings)
        self.calls = []
        self.tags = []

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self.calls.append(_call())
        self.tags.append(cache_tag)
        if result_model is not None:
            return {}
        return copy.deepcopy(self._readings[0])


def _gate_reading(total=100.0):
    return {"documents": [
        {"doc_type": "receipt", "currency": "JPY", "country": "JP",
         "total_amount": total, "inpatient": False,
         "line_items": [{"description": "care", "amount": 100.0,
                         "category": "consultation"}]},
        {"doc_type": "medical_certificate", "diagnoses": []},
    ]}


def test_gate_pair_clean_agree_passes_without_reread(tmp_path):
    from claimlens import gate_eval

    both = [_gate_reading(), _gate_reading()]
    record = gate_eval.run_pair(
        _gate_case(tmp_path), 1, lambda: _GateStub(both))
    assert record["agree"] is True
    assert record["stopped"] is False
    assert len(record["calls"]) == 2
    assert record["values"][0]["total"] == 100.0


def test_gate_pair_total_check_stops_agreeing_wrong_total(tmp_path):
    from claimlens import gate_eval

    both = [_gate_reading(999999.0), _gate_reading(999999.0)]
    record = gate_eval.run_pair(
        _gate_case(tmp_path), 1, lambda: _GateStub(both))
    assert record["agree"] is True
    assert record["stopped_each"] == [True, True]
    assert record["stopped"] is True
    assert record["reached"] == 0
    assert len(record["calls"]) == 4


def _hard_stub(base, reread):
    stub = SimpleNamespace(name="stub", calls=[], _base=base, _reread=reread)

    def _read(images, instructions, schema, result_model=None, cache_tag=""):
        stub.calls.append(_call())
        if result_model is not None:
            return copy.deepcopy(stub._reread)
        return copy.deepcopy(stub._base)

    stub.read_documents = _read
    return stub


def test_hard_run_once_stops_on_stubborn_total(tmp_path, monkeypatch):
    from claimlens import hard_eval
    from claimlens.engine import load_scenarios
    from claimlens.eval import ground_truth

    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    (tmp_path / "cache").mkdir()
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    images = [_stamp(tmp_path / "receipt.png"), _stamp(tmp_path / "cert.png")]
    base = {"documents": [
        {**_c_like(), "pii": []},
        {"doc_type": "medical_certificate", "diagnoses": [], "pii": []},
    ]}
    stub = _hard_stub(base, {"total_amount": 0.0})
    scenarios, _ = load_scenarios()
    truth = ground_truth(scenarios["C_newyork_panic"])
    record = hard_eval.run_once(
        "C_newyork_panic", images, truth,
        {"total": False, "line_amounts": False, "kr_cells": []},
        tmp_path / "cache", live_dir, False, lambda: stub)
    assert record["provider"] == "stub"
    assert record["checks_first"] == "FAIL"
    assert record["verify"]["status"] == "needs_manual_check"
    assert record["stopped"] is True
    assert record["reached"] == 0


def test_hard_run_once_repairs_total(tmp_path, monkeypatch):
    from claimlens import hard_eval
    from claimlens.engine import load_scenarios
    from claimlens.eval import ground_truth

    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    (tmp_path / "cache").mkdir()
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    images = [_stamp(tmp_path / "receipt.png"), _stamp(tmp_path / "cert.png")]
    base = {"documents": [
        {**_c_like(), "pii": []},
        {"doc_type": "medical_certificate", "diagnoses": [], "pii": []},
    ]}
    stub = _hard_stub(base, {"total_amount": 3200.0})
    scenarios, _ = load_scenarios()
    truth = ground_truth(scenarios["C_newyork_panic"])
    record = hard_eval.run_once(
        "C_newyork_panic", images, truth,
        {"total": False, "line_amounts": False, "kr_cells": []},
        tmp_path / "cache", live_dir, False, lambda: stub)
    assert record["verify"]["status"] == "verified"
    assert record["verify"]["corrected"] == ["total_amount"]
    assert record["stopped"] is False
