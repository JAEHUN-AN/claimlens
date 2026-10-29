"""49 unseen set: truth consistency, deterministic render, gate-eval wiring."""

import copy
import json
import sys
from pathlib import Path

from PIL import Image

from claimlens import gate_eval
from claimlens.cli import main
from claimlens.eval import ground_truth
from claimlens.hard_eval import BASE_EST, PROBE_EST, REREAD_EST
from claimlens.providers.meta import CallRecord
from claimlens.rotation import RotationProbe

ROOT = Path(__file__).resolve().parent.parent
UNSEEN = ROOT / "samples" / "unseen"

sys.path.insert(0, str(ROOT / "tools" / "unseen"))
import render


def _truth():
    return json.loads((UNSEEN / "truth.json").read_text(encoding="utf-8"))


def test_truth_is_self_consistent():
    scenarios = _truth()["scenarios"]
    assert [s["id"] for s in scenarios] == [
        "U1_hanbit_outpatient", "U2_mirae_inpatient", "U3_naha_clinic",
        "U4_denver_bill", "U5_pudong_receipt", "U6_austin_urgent",
    ]
    for scenario in scenarios:
        receipt = scenario["documents"][0]["data"]
        assert scenario["documents"][0]["doc_type"] == "receipt"
        assert scenario["documents"][1]["doc_type"] == "medical_certificate"
        assert scenario["documents"][1]["data"]["diagnoses"]
        assert scenario["patient"]["name"] and scenario["patient"]["dob"]
        assert "(SYNTHETIC)" in receipt["address"]
        assert abs(sum(i["amount"] for i in receipt["items"])
                   - scenario["expected"]["total"]) < 0.01
        assert receipt["currency"] == scenario["expected"]["currency"]
        assert (UNSEEN / scenario["id"]).is_dir()
    u2 = scenarios[1]["documents"][0]["data"]
    for item in u2["items"]:
        assert abs(item["qty"] * item["unit"] - item["amount"]) < 0.01
    u3 = scenarios[2]["documents"][0]["data"]
    assert u3["items"][-1]["amount"] == 610  # the tax line is a truth item
    assert u3["subtotal"] + 610 == u3["total"]
    u4 = scenarios[3]["documents"][0]["data"]
    assert u4["items"][-1]["amount"] == -212.5  # total = charges + adjustment
    assert u4["subtotal"] - 212.5 == u4["total"]


def test_ground_truth_covers_unseen():
    for scenario in _truth()["scenarios"]:
        truth = ground_truth(scenario)
        assert truth["total"] == scenario["expected"]["total"]
        assert truth["currency"] == scenario["expected"]["currency"]
        assert truth["kr_cells"] is None  # no circled cells on unseen forms
        assert truth["line_amounts"] == [
            float(i["amount"]) for i in scenario["documents"][0]["data"]["items"]
        ]


def test_render_is_deterministic(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    assert render.main(["--out", str(first)]) == 0
    assert render.main(["--out", str(second)]) == 0
    pngs = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    assert len(pngs) == 24
    for rel in pngs:
        assert (second / rel).read_bytes() == (first / rel).read_bytes()


def test_committed_images_match_layout():
    for scenario in _truth()["scenarios"]:
        case_dir = UNSEEN / scenario["id"]
        for name in ("receipt_clean.png", "receipt_photo.jpg",
                     "medical_certificate_clean.png",
                     "medical_certificate_photo.jpg"):
            path = case_dir / name
            assert path.exists(), path
            with Image.open(path) as img:
                img.load()
                assert img.size == (1240, 1754)
        clean = (case_dir / "receipt_clean.png").read_bytes()
        photo = (case_dir / "receipt_photo.jpg").read_bytes()
        assert clean != photo


def test_readme_lists_every_font_file():
    readme = (UNSEEN / "README.md").read_text(encoding="utf-8")
    assert "uv run python tools/unseen/render.py" in readme
    for pair in render.FONTS.values():
        for name, _ in pair:
            assert name in readme, name


def test_unseen_plan_has_both_variants():
    plan = gate_eval.plan_unseen(UNSEEN)
    assert len(plan["cases"]) == 12
    assert plan["cases"][0] == {"sample": "U1_hanbit_outpatient",
                                "variant": "photo"}
    assert {c["variant"] for c in plan["cases"]} == {"photo", "clean"}
    one = gate_eval.plan_unseen(UNSEEN, ("U4_denver_bill",))
    assert [c["sample"] for c in one["cases"]] == ["U4_denver_bill"] * 2


def test_unseen_estimate_counts_reads_probes_rereads():
    text = gate_eval.estimate_text("unseen", 12, 3, 2)
    assert "12 cases x3 = 36 pairs" in text
    assert "72 reads + up to 72 verify re-reads + 72 rotation probes" in text
    lo = 72 * BASE_EST + 72 * PROBE_EST
    assert f"${lo:.2f}" in text
    assert f"${lo + 72 * REREAD_EST:.2f}" in text


def test_gate_eval_unseen_plan_only(capsys):
    assert main(["gate-eval", "--set", "unseen"]) == 0
    out = capsys.readouterr().out
    assert "unseen: 12 cases x3 = 36 pairs" in out
    assert "72 rotation probes" in out
    assert "Stopped before any API call" in out
    assert main(["gate-eval", "--set", "unseen",
                 "--samples", "U1_hanbit_outpatient"]) == 0
    assert "unseen: 2 cases x3" in capsys.readouterr().out


def test_gate_eval_unseen_rejects_unknown_sample(capsys):
    assert main(["gate-eval", "--set", "unseen",
                 "--samples", "U9_nope"]) == 2
    assert "unknown: U9_nope" in capsys.readouterr().err


class _UnseenStub:
    """Agrees with itself; probes say upright; readings match unseen truth."""

    def __init__(self, readings):
        self._readings = readings
        self.calls = []
        self.probes = 0

    def read_documents(self, images, instructions, schema, result_model=None,
                       cache_tag=""):
        self.calls.append(CallRecord(model="stub", input_tokens=100,
                                     output_tokens=0, total_tokens=100,
                                     cost_usd=0.01))
        if result_model is RotationProbe:
            self.probes += 1
            return {"rotation": 0}
        if result_model is not None:
            return {}
        return copy.deepcopy(self._readings.pop(0))


def _reading_for(truth):
    receipt = {
        "currency": truth["currency"], "total_amount": truth["total"],
        "service_date": "2026-09-15", "inpatient": False,
        "line_items": [{"label": f"line {n}", "amount": a}
                       for n, a in enumerate(truth["line_amounts"])],
        "institution": {"name": "x", "address": "y"},
        "patient": {"name": "P", "date_of_birth": "2000-01-01",
                    "passport": "X", "patient_id": "Y"},
    }
    cert = dict(receipt)
    cert["diagnoses"] = [{"label": "d", "code": c} for c in truth["diag_codes"]]
    return {"documents": [receipt, cert]}


def test_gate_execute_unseen_probes_and_scores(tmp_path, monkeypatch):
    from claimlens import hard_eval

    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    scenarios = gate_eval.load_unseen_scenarios(UNSEEN)
    plan = gate_eval.plan_unseen(UNSEEN, ("U1_hanbit_outpatient",))
    stubs = []
    for case in plan["cases"]:
        truth = ground_truth(scenarios[case["sample"]])
        case["images"] = [UNSEEN / case["sample"] / "receipt_photo.jpg",
                          UNSEEN / case["sample"] / "medical_certificate_photo.jpg"]
        case["truth"] = truth
        case["unreadable"] = {"total": False, "line_amounts": False,
                              "kr_cells": []}
        case["key"] = f"{case['sample']}-{case['variant']}"

    def _factory():
        stub = _UnseenStub([_reading_for(plan["cases"][0]["truth"])] * 60)
        stubs.append(stub)
        return stub

    results = gate_eval.execute({"unseen": {**plan, "probe": True}}, 3, 99.0,
                              _factory, tmp_path / "out")
    unseen = results["sets"]["unseen"]
    assert unseen["pairs"] == 2 * 3
    assert unseen["leaks"] == 0
    assert unseen["stops"] == 0
    assert unseen["per_claim"] == unseen["spent"] / unseen["pairs"]
    assert sum(s.probes for s in stubs) == 2 * 3 * 2  # both pages, every pair
    assert all(p["rotation"] == [] for p in unseen["pair_details"])
    assert results["spent"] == unseen["spent"]
    assert hard_eval.git_cache_status() == "(clean)"


def test_gate_pair_unseen_marks_leaks():
    truth = ground_truth(gate_eval.load_unseen_scenarios(UNSEEN)["U4_denver_bill"])
    wrong = _reading_for(truth)
    # Subtotal read as the total, first line shifted to match: checks pass,
    # both sides agree, the wrong numbers leave.
    wrong["documents"][0]["total_amount"] = 4250.0
    wrong["documents"][0]["line_items"][0]["amount"] = 2062.5
    case = {"sample": "U4_denver_bill", "variant": "photo", "key": "U4-photo",
            "images": [UNSEEN / "U4_denver_bill" / "receipt_photo.jpg",
                       UNSEEN / "U4_denver_bill" / "medical_certificate_photo.jpg"],
            "truth": truth,
            "unreadable": {"total": False, "line_amounts": False, "kr_cells": []}}
    record = gate_eval.run_pair(case, 1, lambda: _UnseenStub([wrong, wrong]),
                                probe_pages=True)
    assert record["agree"] is True
    assert record["stopped"] is False
    assert record["reached"] == 2
    assert record["wrong_fields"] == ["total", "lines[0]"]
