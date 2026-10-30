"""Hard-set eval tests: seeded images, honest-null scoring, no cache writes."""

import copy
import hashlib
import io
import json
import random
from pathlib import Path

from PIL import Image

from claimlens import hard_eval
from claimlens.eval import ground_truth, load_scenarios
from claimlens.hard_images import (
    HARD_SAMPLES,
    TRANSFORMS,
    apply_transform,
    ensure_hard_set,
    seed_for,
)
from claimlens.providers.meta import CallRecord

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


def _snap() -> Image.Image:
    return Image.open(SAMPLES / "S2_seoul_worker_bronchitis" / "receipt_photo.jpg")


def _shot(img: Image.Image, seed: int, transform: str, kind: str = "kr") -> bytes:
    out = apply_transform(img.convert("RGB"), transform, random.Random(seed), kind)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def test_seed_stable_and_case_unique():
    assert seed_for(41, "S2", "crop") == seed_for(41, "S2", "crop")
    assert len({seed_for(41, s, t) for s in HARD_SAMPLES for t in TRANSFORMS}) == (
        len(HARD_SAMPLES) * len(TRANSFORMS)
    )


def test_every_transform_is_deterministic():
    img = _snap()
    for transform in TRANSFORMS:
        first = _shot(img, 41, transform)
        second = _shot(img, 41, transform)
        assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


def test_jittered_transforms_vary_with_seed():
    img = _snap()
    for transform in ("perspective", "lowlight", "glare"):
        assert _shot(img, 41, transform) != _shot(img, 42, transform)


def test_manifest_marks_and_files(tmp_path):
    manifest = ensure_hard_set(41, tmp_path, SAMPLES)
    assert len(manifest["cases"]) == len(HARD_SAMPLES) * len(TRANSFORMS)
    assert (tmp_path / "manifest.json").exists()
    by_key = {(c["sample"], c["transform"]): c for c in manifest["cases"]}
    s2_crop = by_key[("S2_seoul_worker_bronchitis", "crop")]
    assert s2_crop["unreadable"] == {"total": True, "line_amounts": False,
                                     "kr_cells": [6, 7, 8, 9, 10]}
    a_crop = by_key[("A_niseko_wrist", "crop")]
    assert a_crop["unreadable"] == {"total": True, "line_amounts": True, "kr_cells": []}
    assert by_key[("S2_seoul_worker_bronchitis", "glare")]["unreadable"]["kr_cells"] == []
    for case in manifest["cases"]:
        assert (tmp_path / case["receipt"]).exists()
        assert (tmp_path / case["cert"]).exists()
    again = ensure_hard_set(41, tmp_path, SAMPLES)
    assert again == manifest


def test_crop_geometry_keeps_scored_neighbors(tmp_path):
    ensure_hard_set(41, tmp_path, SAMPLES,
                    samples=("S2_seoul_worker_bronchitis", "A_niseko_wrist"),
                    transforms=("crop",))
    s2 = Image.open(tmp_path / "receipt_S2_seoul_worker_bronchitis_crop.jpg")
    assert s2.size[0] < _snap().size[0]  # true right crop
    a = Image.open(tmp_path / "receipt_A_niseko_wrist_crop.jpg")
    assert a.size == Image.open(SAMPLES / "A_niseko_wrist" / "receipt_photo.jpg").size


def _s2_truth():
    return ground_truth(load_scenarios()["S2_seoul_worker_bronchitis"])


def _s2_reading(**overrides):
    from claimlens.eval import load_scenarios as _load

    truth = _s2_truth()
    items = _load()["S2_seoul_worker_bronchitis"]["documents"][0]["data"]["items"]
    cells = {f"cell_{n}": v for n, v in enumerate(truth["kr_cells"], start=1)}
    bill = {"institution_type": truth["institution"], **cells,
            "charge_rows": [{"label": f"row{i}", "col_1": it.get("copay", 0),
                             "col_2": it.get("insurer", 0), "col_3": it.get("full", 0),
                             "col_4": it.get("non_covered", 0)} for i, it in enumerate(items)]}
    receipt = {"doc_type": "receipt", "currency": "KRW", "country": "KR", "total_amount": truth["total"], "inpatient": False,
               "line_items": [{"description": f"d{i}", "category": "lab", "amount": a}
                              for i, a in enumerate(truth["line_amounts"])],
               "diagnoses": [], "pii": [], "kr_bill": bill}
    receipt.update(overrides.get("receipt", {}))
    if "bill" in overrides:
        receipt["kr_bill"].update(overrides["bill"])
    cert = {"doc_type": "medical_certificate", "currency": "",
            "diagnoses": [{"code": c} for c in truth["diag_codes"]], "pii": []}
    return {"documents": [receipt, cert]}


class _Stub:
    name = "stub"

    def __init__(self, readings, reread=None):
        self._readings = list(readings)
        self._reread = reread if reread is not None else {}
        self.calls = []

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self.calls.append(CallRecord(model="stub", input_tokens=5000, output_tokens=500,
                                     total_tokens=5500, cost_usd=0.01))
        if result_model is not None:
            return copy.deepcopy(self._reread)
        reading = self._readings.pop(0) if len(self._readings) > 1 else self._readings[0]
        return copy.deepcopy(reading)


def _run(readings, truth=None, unreadable=None, reread=None, sample="S2_seoul_worker_bronchitis"):
    truth = truth if truth is not None else _s2_truth()
    stub = _Stub(readings, reread)
    record = hard_eval.run_once(
        sample, [SAMPLES / sample / "receipt_photo.jpg",
                 SAMPLES / sample / "medical_certificate_photo.jpg"],
        truth, unreadable or {"total": False, "line_amounts": False, "kr_cells": []},
        None, Path("unused-tmp"), True, lambda: stub,
    )
    return record, stub


def test_perfect_reading_needs_no_verify():
    record, stub = _run([_s2_reading()])
    assert record["checks_first"] == "pass"
    assert record["verify"] is None
    assert record["stopped"] is False
    assert record["reached"] == 0
    assert len(stub.calls) == 1
    assert record["final"]["kr_cells"] == "10/10"


def test_reread_recovery_counts_and_reaches_zero():
    broken = _s2_reading(bill={"cell_6": 1})
    fixed = {"cell_6": _s2_truth()["kr_cells"][5]}
    record, stub = _run([broken], reread=fixed)
    assert record["checks_first"] == "FAIL"
    assert record["verify"]["status"] == "verified"
    assert record["verify"]["corrected"] == ["cell_6"]
    assert record["reached"] == 0
    assert len(stub.calls) == 2


def test_unrecovered_wrong_numbers_stop_without_reaching():
    broken = _s2_reading(bill={"cell_6": 1})
    record, _ = _run([broken], reread={"cell_6": 1})
    assert record["verify"]["status"] == "needs_manual_check"
    assert record["stopped"] is True
    assert record["wrong_numbers"] > 0
    assert record["reached"] == 0


def test_crop_nulls_stop_cleanly_and_score_right():
    nulls = {f"cell_{n}": None for n in (6, 7, 8, 9, 10)}
    reading = _s2_reading(receipt={"total_amount": None}, bill=nulls)
    unreadable = {"total": True, "line_amounts": False, "kr_cells": [6, 7, 8, 9, 10]}
    record, _ = _run([reading], unreadable=unreadable, reread=dict(nulls))
    assert record["base"]["total"] == "ok"
    assert record["base"]["kr_cells"] == "10/10"
    assert record["base"]["guesses"] == 0
    assert record["stopped"] is True
    assert record["reached"] == 0


def test_crop_guesses_count_as_wrong():
    nulls = {f"cell_{n}": None for n in (7, 8, 9, 10)}
    reading = _s2_reading(receipt={"total_amount": 123.0}, bill={"cell_6": 7, **nulls})
    unreadable = {"total": True, "line_amounts": False, "kr_cells": [6, 7, 8, 9, 10]}
    assert hard_eval.compare_hard("S2_seoul_worker_bronchitis", _s2_truth(),
                                  reading, unreadable)["guesses"] == 2


def test_non_kr_wrong_numbers_reach_when_checks_pass():
    scenarios = load_scenarios()
    truth = ground_truth(scenarios["A_niseko_wrist"])
    reading = {"documents": [
        {"doc_type": "receipt", "currency": "JPY", "country": "JP", "total_amount": 1.0, "inpatient": False,
         "line_items": [{"description": "x", "category": "lab", "amount": 1.0}],
         "diagnoses": [], "pii": [], "kr_bill": None},
        {"doc_type": "medical_certificate", "currency": "",
         "diagnoses": [{"code": c} for c in truth["diag_codes"]], "pii": []},
    ]}
    record, _ = _run([reading], truth=truth, sample="A_niseko_wrist")
    assert record["checks_first"] == "pass"
    assert record["verify"] is None
    assert record["stopped"] is False
    assert record["reached"] == record["wrong_numbers"] > 0


def test_summarize_agreement_and_pipeline():
    good = _s2_reading()
    bad = _s2_reading(bill={"cell_6": 1})
    fixed = {"cell_6": _s2_truth()["kr_cells"][5]}
    truth = _s2_truth()
    unreadable = {"total": False, "line_amounts": False, "kr_cells": []}
    images = [SAMPLES / "S2_seoul_worker_bronchitis" / "receipt_photo.jpg",
              SAMPLES / "S2_seoul_worker_bronchitis" / "medical_certificate_photo.jpg"]
    runs = []
    for reading, reread in ((good, fixed), (bad, {"cell_6": 1}), (good, fixed)):
        stub = _Stub([reading], reread)
        record = hard_eval.run_once("S2_seoul_worker_bronchitis", images, truth,
                                    unreadable, None, Path("unused-tmp"), True,
                                    lambda s=stub: s)
        runs.append(record)
    summary = hard_eval.summarize([{"sample": "S2", "runs": runs, "truth": truth}], 3)
    assert summary["accuracy"]["total"] == {"ok": 1, "n": 1}
    assert summary["agree"]["total"] == {"agree": 1, "n": 1}
    assert summary["agree"]["kr_cells"] == {"agree": 0, "n": 1}
    assert summary["recovered"] == {"recovered": 0, "reread": 1}
    assert summary["caught"] == {"caught": 1, "base_wrong": 1}
    assert summary["stopped"] == {"stopped": 1, "correct": 1, "n": 3}
    assert summary["reached"] == 0
    gate = hard_eval.simulate_gate([{"runs": runs}])
    assert gate == {"pairs": 3, "stops": 2, "leaks": 0}
    summary["gate"] = gate
    text = hard_eval.format_tables({"sets": {"hard": summary}, "spent": 0.03,
                                    "aborted": False}, 3)
    assert "wrong numbers that left the pipeline (decision or claim pack)" in text
    assert "| **0** | **0** |" in text
    assert "simulated from the recorded run pairs" in text
    assert "/ $0.0400 |" in text


def test_kr_only_fields_skip_non_kr_cases():
    scenarios = load_scenarios()
    truth = ground_truth(scenarios["A_niseko_wrist"])
    reading = {"documents": [
        {"doc_type": "receipt", "currency": "JPY", "country": "JP", "total_amount": truth["total"], "inpatient": False,
         "line_items": [{"description": f"d{i}", "category": "lab", "amount": a}
                        for i, a in enumerate(truth["line_amounts"])],
         "diagnoses": [], "pii": [], "kr_bill": None},
        {"doc_type": "medical_certificate", "currency": "",
         "diagnoses": [{"code": c} for c in truth["diag_codes"]], "pii": []},
    ]}
    images = [SAMPLES / "A_niseko_wrist" / "receipt_photo.jpg",
              SAMPLES / "A_niseko_wrist" / "medical_certificate_photo.jpg"]
    runs = []
    for _ in range(3):
        stub = _Stub([reading])
        runs.append(hard_eval.run_once(
            "A_niseko_wrist", images, truth,
            {"total": False, "line_amounts": False, "kr_cells": []},
            None, Path("unused-tmp"), True, lambda s=stub: s))
    summary = hard_eval.summarize([{"sample": "A", "runs": runs, "truth": truth}], 3)
    assert summary["accuracy"]["kr_cells"] == {"ok": 0, "n": 0}
    assert summary["accuracy"]["instit"] == {"ok": 0, "n": 0}
    assert summary["agree"]["kr_cells"] == {"agree": 0, "n": 0}
    assert summary["accuracy"]["total"] == {"ok": 1, "n": 1}


def test_plan_counts_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    plan = hard_eval.plan_hard(41, tmp_path / "hard", SAMPLES, 3,
                               ("A_niseko_wrist",), ("crop", "glare"))
    assert len(plan["cases"]) == 2
    assert plan["base_live"] == 2 + 2 * 2
    assert plan["base_replay"] == 0
    assert plan["reread_max"] == 2 * 3
    text = hard_eval.estimate_text(plan, "hard set x3")
    assert "6 live + 0 replay" in text
    assert "narrow re-reads: up to 6" in text
    assert text.count("$") >= 2


def test_plan_normal_replays_run_one():
    plan = hard_eval.plan_normal(SAMPLES, 3, ("A_niseko_wrist",))
    assert len(plan["cases"]) == 2
    assert plan["base_live"] == 2 * 2
    assert plan["base_replay"] == 2
    assert all(c["cached"] for c in plan["cases"])


def test_read2_plan_and_record_use_new_keys_only(tmp_path, monkeypatch):
    import shutil

    from claimlens import cache as replay_cache

    mirror = tmp_path / "cache"
    shutil.copytree(ROOT / "cache", mirror, ignore=shutil.ignore_patterns("live"))
    for stale in mirror.glob("*.read2.json"):
        stale.unlink()
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(mirror))
    before = sorted(p.name for p in mirror.glob("*.json"))
    assert not [n for n in before if n.endswith(".read2.json")]
    plan = hard_eval.plan_read2(SAMPLES, ("A_niseko_wrist",))
    assert plan["missing"] == 2

    class _Canned:
        def __init__(self):
            from types import SimpleNamespace

            payload = json.dumps({"documents": []})
            self.responses = SimpleNamespace(
                create=lambda **kw: SimpleNamespace(
                    output_text=payload,
                    usage=SimpleNamespace(input_tokens=5, output_tokens=1, total_tokens=6),
                )
            )

    from claimlens.providers.meta import MetaProvider

    def _factory():
        provider = MetaProvider(api_key="test-key", live=False)
        provider._client = _Canned()
        provider._resolve_file_ids = lambda blobs: None
        return provider

    done = hard_eval.record_read2(plan["pairs"], SAMPLES, _factory)
    assert done["stored"] == ["A_niseko_wrist photo", "A_niseko_wrist clean"]
    after = sorted(p.name for p in mirror.glob("*.json"))
    assert len(after) == len(before) + 2
    assert all(n in after for n in before)
    assert sum(n.endswith(".read2.json") for n in after) == 2
    for pair in plan["pairs"]:
        assert replay_cache.cache_path(pair["key"]).exists()
    rerun = hard_eval.plan_read2(SAMPLES, ("A_niseko_wrist",))
    assert rerun["missing"] == 0


def test_execute_stub_writes_no_committed_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    before = sorted((ROOT / "cache").rglob("*"))
    manifest = ensure_hard_set(41, tmp_path / "hard", SAMPLES,
                               samples=("A_niseko_wrist",), transforms=("rot90",))
    case = manifest["cases"][0]
    truth = ground_truth(load_scenarios()["A_niseko_wrist"])
    stub = _Stub([_s2_reading()])
    plans = {"hard": {"cases": [{
        **case,
        "images": [tmp_path / "hard" / case["receipt"], tmp_path / "hard" / case["cert"]],
        "truth": truth, "unreadable": case["unreadable"]}], "base_live": 3,
        "base_replay": 0, "reread_max": 0}}
    results = hard_eval.execute(plans, 3, 1.00, lambda: stub, tmp_path / "log.json")
    assert (tmp_path / "log.json").exists()
    assert json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))["spent"] > 0
    assert results["sets"]["hard"]["agree"]["total"] == {"agree": 1, "n": 1}
    assert sorted((ROOT / "cache").rglob("*")) == before
    assert results["cache_before"] == results["cache_after"]


def _plain_unreadable():
    return {"total": False, "line_amounts": False, "kr_cells": []}


def test_wrong_numeric_fields_names_lines_and_count_parity():
    truth = {"total": 100, "line_amounts": [60, 40], "kr_cells": None}

    def reading(lines, total=100):
        return {"documents": [{"total_amount": total,
                               "line_items": [{"amount": a} for a in lines]}]}

    cases = [
        ([60, 40], []),
        ([60, 41], ["lines[1]"]),
        ([60], ["lines[1]"]),
        ([60, 40, 5], ["lines[2]"]),
    ]
    for lines, expected in cases:
        got = hard_eval.wrong_numeric_fields(truth, reading(lines), _plain_unreadable())
        assert got == expected
        assert hard_eval._numeric_wrongs(truth, reading(lines), _plain_unreadable()) == len(got)
    got = hard_eval.wrong_numeric_fields(truth, reading([60, 40], total=101),
                                          _plain_unreadable())
    assert got == ["total"]


def test_wrong_numeric_fields_kr_and_cut_cell_guesses():
    truth = {"total": 100, "line_amounts": [100],
             "kr_cells": [10 * n for n in range(1, 11)]}
    bill = {f"cell_{n}": 10 * n for n in range(1, 11)}
    bill["cell_3"] = 31

    def reading():
        return {"documents": [{"total_amount": 100, "line_items": [{"amount": 100}],
                               "kr_bill": dict(bill)}]}

    assert hard_eval.wrong_numeric_fields(truth, reading(), _plain_unreadable()) == [
        "kr_cells[3]"]
    cut = {"total": False, "line_amounts": False, "kr_cells": [3]}
    assert hard_eval.wrong_numeric_fields(truth, reading(), cut) == ["kr_cells[3]"]
    bill["cell_3"] = None
    assert hard_eval.wrong_numeric_fields(truth, reading(), cut) == []


def test_null_line_amount_is_wrong_not_a_crash():
    from claimlens import hard_eval

    truth = {"total": 300.0, "line_amounts": [100.0, 200.0], "kr_cells": None}
    reading = {"documents": [{"total_amount": 300.0,
                              "line_items": [{"amount": 100.0}, {"amount": None}]}]}
    assert hard_eval.wrong_numeric_fields(truth, reading, {}) == ["lines[1]"]


def _c1_truth():
    return {"total": 235000.0, "line_amounts": [235000.0], "kr_cells": None,
            "currency": "JPY", "country": "JP", "inpatient": False,
            "diag_codes": ["S62.0"], "charge_rows": None}


def _c1_reading(**overrides):
    receipt = {"currency": "JPY", "country": "JP", "total_amount": 235000.0,
               "inpatient": False,
               "line_items": [{"description": "care", "category": "other",
                               "amount": 235000.0}]}
    diags = overrides.pop("diags", ["S62.0"])
    receipt.update(overrides)
    cert = {"diagnoses": [{"code": c} for c in diags]}
    return {"documents": [receipt, cert]}


def test_wrong_numeric_fields_scores_c1_identity():
    """C1: currency, country, stay, and codes join the leak metric."""
    truth = _c1_truth()
    assert hard_eval.wrong_numeric_fields(truth, _c1_reading(), {}) == []
    cases = [
        ({"currency": "USD"}, ["currency"]),
        ({"country": "KR"}, ["country"]),
        ({"inpatient": True}, ["inpatient"]),
        ({"diags": ["S62.1"]}, ["diag_codes[0]"]),
        ({"diags": []}, ["diag_codes[0]"]),
    ]
    for override, expected in cases:
        got = hard_eval.wrong_numeric_fields(truth, _c1_reading(**override), {})
        assert got == expected, override


def test_wrong_numeric_fields_scores_charge_rows():
    """C1: KR charge-row cells join the leak metric."""
    truth = {"total": 100.0, "line_amounts": [100.0],
             "kr_cells": [100, 0, 0, 0, 0, 100, 0, 100, 0, 100],
             "currency": "KRW", "country": "KR", "inpatient": False,
             "diag_codes": ["J20.9"], "charge_rows": [[100, 0, 0, 0]]}
    good = {"documents": [
        {"currency": "KRW", "country": "KR", "total_amount": 100.0,
         "inpatient": False, "line_items": [{"amount": 100.0}],
         "kr_bill": {f"cell_{n}": v for n, v in
                     enumerate([100, 0, 0, 0, 0, 100, 0, 100, 0, 100], start=1)}
         | {"charge_rows": [{"label": "a", "col_1": 100, "col_2": 0,
                             "col_3": 0, "col_4": 0}]}},
        {"diagnoses": [{"code": "J20.9"}]},
    ]}
    assert hard_eval.wrong_numeric_fields(truth, good, {}) == []
    bad = copy.deepcopy(good)
    bad["documents"][0]["kr_bill"]["charge_rows"][0]["col_2"] = 5
    assert hard_eval.wrong_numeric_fields(truth, bad, {}) == [
        "charge_rows[0].col_2"]


def test_gate_agree_covers_c1_fields():
    """C1: reads disagreeing on identity fields never pass the gate."""
    base = {"total": 1.0, "lines": [1.0], "kr_cells": None, "currency": "JPY",
            "country": "JP", "service_date": "2026-08-12", "inpatient": False,
            "diags": ["S62.0"], "charge_rows": None}
    assert hard_eval._gate_agree(base, dict(base)) is True
    for field, other in (("currency", "USD"), ("country", "KR"),
                         ("service_date", "2026-08-13"), ("inpatient", True),
                         ("diags", ["S62.1"]), ("charge_rows", [[1]])):
        left, right = dict(base), dict(base)
        right[field] = other
        assert hard_eval._gate_agree(left, right) is False, field


def test_ground_truth_carries_c1_fields():
    """C1: country, stay, and charge rows come from scenario data."""
    s2 = ground_truth(load_scenarios()["S2_seoul_worker_bronchitis"])
    assert s2["country"] == "KR"
    assert s2["inpatient"] is False
    assert len(s2["charge_rows"]) == 5
    assert s2["charge_rows"][0] == [9000, 9000, 0, 0]
    a = ground_truth(load_scenarios()["A_niseko_wrist"])
    assert a["country"] == "JP"
    assert a["inpatient"] is False
    assert a["charge_rows"] is None


def test_adjustment_lines_score_as_the_truth_lines():
    # Truth lists a discount as a line; the pipeline reads it as an adjustment line.
    from claimlens import hard_eval

    truth = {"total": 4037.5, "line_amounts": [4250.0, -212.5], "kr_cells": None}
    reading = {"documents": [{"total_amount": 4037.5, "line_items": [{"amount": 4250.0}],
                              "adjustment_lines": [{"kind": "discount", "amount": -212.5}]}]}
    assert hard_eval.wrong_numeric_fields(truth, reading, {}) == []
    wrong_adj = copy.deepcopy(reading)
    wrong_adj["documents"][0]["adjustment_lines"][0]["amount"] = -21.25
    assert hard_eval.wrong_numeric_fields(truth, wrong_adj, {}) == ["lines[1]"]
