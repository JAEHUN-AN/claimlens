"""49b trips: truth consistency, deterministic render, gate + serve wiring."""

import base64
import copy
import json
import sys
from pathlib import Path

from PIL import Image

from claimlens import gate_eval, trips_check
from claimlens.cli import main
from claimlens.eligibility import check_eligibility
from claimlens.eval import ground_truth
from claimlens.hard_eval import BASE_EST, PROBE_EST, REREAD_EST
from claimlens.providers.meta import CallRecord
from claimlens.rotation import RotationProbe
from claimlens.serve import missing_facts

ROOT = Path(__file__).resolve().parent.parent
TRIPS = ROOT / "samples" / "unseen" / "trips"

sys.path.insert(0, str(ROOT / "tools" / "unseen"))
import render

IDS = [
    "T1_bangkok_food_poisoning", "T2_danang_scooter", "T3_setagaya_fever",
    "T4_paris_pharmacy", "T5_honolulu_urgent", "T6_guam_dental",
]


def _truth():
    return json.loads((TRIPS / "truth.json").read_text(encoding="utf-8"))


def _fx():
    return json.loads((ROOT / "samples" / "fx_demo.json").read_text(encoding="utf-8"))


def test_truth_is_self_consistent():
    cases = _truth()["cases"]
    assert [c["id"] for c in cases] == IDS
    for case in cases:
        # H1: Korean nationals treated abroad take the traveller engine
        # path (serve-level; the NHI rows alone still say row3).
        assert case["eligibility_path"] == "traveller_abroad (engine_path)"
        assert case["currency"]
        assert case["patient"]["name"] and case["patient"]["dob"]
        assert case["expected"]["ideal"]
        for doc in case["documents"]:
            data = doc["data"]
            if "address" in data:
                assert "(SYNTHETIC)" in data["address"]
            elif doc["role"] == "payment":
                assert data["hospital"]  # the slip names its merchant instead
            else:
                assert doc["role"] == "certificate"  # watermark still marks it
            if doc["role"] in ("receipt", "bill", "payment"):
                assert data["currency"] == case["currency"]
        # every receipt's total is its own items (+ tax where shown)
        for doc in case["documents"]:
            if doc["role"] not in ("receipt", "bill"):
                continue
            data = doc["data"]
            items = sum(i["amount"] for i in data["items"])
            assert abs(items + data.get("tax", 0) - data["total"]) < 0.01
        # local total = receipts only; the card slip is proof, not a charge
        local = sum(d["data"]["total"] for d in case["documents"]
                    if d["role"] in ("receipt", "bill"))
        assert abs(local - case["totals"]["local"]) < 0.01
        rate = _fx()["rates"][case["currency"]]
        assert case["totals"]["krw"] == round(case["totals"]["local"] * rate)
        # pairs resolve to rendered files
        files = {d["file"] for d in case["documents"]}
        assert case["pairs"]
        for receipt_file, cert_file in case["pairs"]:
            assert receipt_file in files
            assert cert_file is None or cert_file in files
    t4 = cases[3]
    assert t4["pairs"] == [["receipt", None]]  # pharmacy ticket, no certificate
    assert all(d["role"] != "certificate" for d in t4["documents"])
    t5 = cases[4]["documents"][0]["data"]
    assert t5["items"][-1]["amount"] == -571.65  # patient owes charges + adjustment
    assert abs(t5["subtotal"] - 571.65 - t5["total"]) < 0.01
    assert cases[4]["totals"]["local"] == t5["total"]  # slip pays it, not added
    t3 = cases[2]["documents"][0]["data"]
    assert t3["items"][-1]["amount"] == 330  # the consumption-tax line
    assert t3["subtotal"] + 330 == t3["total"]
    t2 = cases[1]["documents"][0]["data"]
    assert t2["total"] == 1186000  # plain number in truth ...
    assert render.fmt_vnd(t2["total"]) == "1.186.000"  # ... dots on the page
    t4data = cases[3]["documents"][0]["data"]
    assert t4data["total"] == 16.50
    assert render.fmt_eur(t4data["total"]) == "16,50"  # comma on the page
    t6 = cases[5]["documents"][0]["data"]
    assert any(i.get("code", "").startswith("D") for i in t6["items"])  # CDT codes


def test_travellers_take_traveller_path():
    from claimlens.eval import country_of_currency
    from claimlens.serve import resolve_eligibility

    want = {
        "T1_bangkok_food_poisoning": "engine_unreachable",
        "T2_danang_scooter": "engine_unreachable",
        "T3_setagaya_fever": "engine_unreachable",
        "T4_paris_pharmacy": "needs_manual_check",
        "T5_honolulu_urgent": "engine_unreachable",
        "T6_guam_dental": "needs_review",
    }
    for case in _truth()["cases"]:
        assert missing_facts(case["person"]) == []  # panel answers are complete
        dates = {d["data"].get("service_date") for d in case["documents"]}
        for service_date in dates:
            # the NHI rows alone still land on row3 for every trip ...
            outcome = check_eligibility(case["person"], service_date)
            assert outcome["outcome"] == "not_member_or_unknown"
        # ... but serve-level eligibility takes the traveller engine path
        country = country_of_currency(case["currency"])
        resolved = resolve_eligibility(case["person"], {"country": country})
        assert (f"{resolved['outcome']} ({resolved['rule']})"
                == case["eligibility_path"])
        serve = case["expected"]["serve_today"]
        assert serve == {"status": 200, "badge": want[case["id"]]}


def test_render_is_deterministic(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    args = ["--truth", str(TRIPS / "truth.json"), "--seed", "49"]
    assert render.main([*args, "--out", str(first)]) == 0
    assert render.main([*args, "--out", str(second)]) == 0
    files = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    assert len(files) == 26
    for rel in files:
        assert (second / rel).read_bytes() == (first / rel).read_bytes()


def test_committed_images_match_layout():
    seen = 0
    for case in _truth()["cases"]:
        case_dir = TRIPS / case["id"]
        for doc in case["documents"]:
            for name in (f"{doc['file']}_clean.png", f"{doc['file']}_photo.jpg"):
                path = case_dir / name
                assert path.exists(), path
                with Image.open(path) as img:
                    img.load()
                    assert img.size == (1240, 1754)
                seen += 1
            clean = (case_dir / f"{doc['file']}_clean.png").read_bytes()
            photo = (case_dir / f"{doc['file']}_photo.jpg").read_bytes()
            assert clean != photo
    assert seen == 26


def test_trips_plan_covers_every_pair():
    plan = gate_eval.plan_trips(TRIPS)
    assert len(plan["cases"]) == 16
    by_sample: dict[str, list] = {}
    for case in plan["cases"]:
        by_sample.setdefault(case["sample"], []).append(case)
    assert sorted(by_sample) == IDS
    assert len(by_sample["T1_bangkok_food_poisoning"]) == 4  # 2 receipts x variants
    assert len(by_sample["T5_honolulu_urgent"]) == 4
    assert len(by_sample["T4_paris_pharmacy"]) == 2
    t4 = by_sample["T4_paris_pharmacy"][0]
    assert t4["cert_file"] is None and t4["pages"] == 1
    assert sum(c["pages"] for c in plan["cases"]) == 30  # T4 reads one page
    one = gate_eval.plan_trips(TRIPS, ("T6_guam_dental",))
    assert [c["sample"] for c in one["cases"]] == ["T6_guam_dental"] * 2


def test_trip_pair_truth_matches_documents():
    cases = gate_eval.load_trip_cases(TRIPS)
    for case in cases.values():
        for receipt_file, cert_file in case["pairs"]:
            scenario = gate_eval.trip_pair_scenario(case, receipt_file, cert_file)
            truth = ground_truth(scenario)
            docs = {d["file"]: d["data"] for d in case["documents"]}
            assert truth["total"] == docs[receipt_file]["total"]
            assert truth["currency"] == case["currency"]
            assert truth["kr_cells"] is None
            assert truth["line_amounts"] == [
                float(i["amount"]) for i in docs[receipt_file]["items"]]
    t4 = gate_eval.trip_pair_scenario(cases["T4_paris_pharmacy"], "receipt", None)
    assert t4["documents"][1]["data"] == {"diagnoses": []}


def test_resolve_trip_images(tmp_path):
    case_dir = TRIPS / "T5_honolulu_urgent"
    pair = gate_eval.resolve_trip_images(case_dir, "receipt_bill", "medical_certificate",
                                         "photo")
    assert [p.name for p in pair] == ["receipt_bill_photo.jpg",
                                      "medical_certificate_photo.jpg"]
    solo = gate_eval.resolve_trip_images(TRIPS / "T4_paris_pharmacy", "receipt", None,
                                          "clean")
    assert [p.name for p in solo] == ["receipt_clean.png"]
    try:
        gate_eval.resolve_trip_images(tmp_path, "receipt", None, "photo")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("missing image must raise")


def test_trips_estimate_counts_pages_not_pairs():
    text = gate_eval.estimate_text("trips", 16, 3, 2, 90)
    assert "16 cases x3 = 48 pairs" in text
    assert "96 reads + up to 96 verify re-reads + 90 rotation probes" in text
    lo = 96 * BASE_EST + 90 * PROBE_EST
    assert f"${lo:.2f}" in text
    assert f"${lo + 96 * REREAD_EST:.2f}" in text
    # the old call shape still works for uniform sets
    assert "72 rotation probes" in gate_eval.estimate_text("unseen", 12, 3, 2)


def test_gate_eval_trips_plan_only(capsys):
    assert main(["gate-eval", "--set", "trips"]) == 0
    out = capsys.readouterr().out
    assert "trips: 16 cases x3 = 48 pairs" in out
    assert "90 rotation probes" in out
    assert "Stopped before any API call" in out
    assert main(["gate-eval", "--set", "trips",
                 "--samples", "T4_paris_pharmacy"]) == 0
    assert "trips: 2 cases x3" in capsys.readouterr().out


def test_gate_eval_trips_rejects_unknown_sample(capsys):
    assert main(["gate-eval", "--set", "trips", "--samples", "T9_nope"]) == 2
    assert "unknown: T9_nope" in capsys.readouterr().err


class _TripStub:
    """Agrees with itself; probes say upright; readings built from trips truth."""

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

    def write(self, instructions, schema, result_model=None):
        self.calls.append(CallRecord(model="stub", input_tokens=50, output_tokens=0,
                                     total_tokens=50, cost_usd=0.01))
        return {"findings": []}


def _reading_for(case, receipt_file, cert_file):
    from claimlens.eval import country_of_currency

    docs = {d["file"]: d["data"] for d in case["documents"]}
    receipt_data = docs[receipt_file]
    receipt = {
        "doc_type": "receipt", "currency": case["currency"],
        "country": country_of_currency(case["currency"]),
        "total_amount": receipt_data["total"], "service_date": "2026-09-18",
        "inpatient": False,
        "line_items": [{"label": f"line {n}", "amount": a}
                       for n, a in enumerate(truth_line_amounts(receipt_data))],
        "institution": {"name": "x", "address": "y"},
        "patient": {"name": "P", "date_of_birth": "2000-01-01",
                    "passport": "X", "patient_id": "Y"},
    }
    diags = docs[cert_file]["diagnoses"] if cert_file else []
    cert = {"doc_type": "medical_certificate",
            "diagnoses": [{"label": "d",
                           "code": c.get("code", c) if isinstance(c, dict) else c}
                          for c in diags]}
    return {"documents": [receipt, cert]}


def truth_line_amounts(receipt_data):
    return [i["amount"] for i in receipt_data["items"]]


def _enriched(case_id, receipt_file, cert_file, variant):
    cases = gate_eval.load_trip_cases(TRIPS)
    truth = ground_truth(gate_eval.trip_pair_scenario(cases[case_id], receipt_file,
                                                       cert_file))
    return {
        "sample": case_id, "variant": variant, "receipt_file": receipt_file,
        "cert_file": cert_file, "key": f"{case_id}-{receipt_file}-{variant}",
        "images": gate_eval.resolve_trip_images(TRIPS / case_id, receipt_file,
                                                 cert_file, variant),
        "truth": truth,
        "unreadable": {"total": False, "line_amounts": False, "kr_cells": []},
    }


def test_gate_execute_trips_probes_and_scores(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    cases = gate_eval.load_trip_cases(TRIPS)
    case = _enriched("T2_danang_scooter", "receipt", "medical_certificate", "photo")
    readings = [_reading_for(cases["T2_danang_scooter"], "receipt",
                             "medical_certificate") for _ in range(2)]
    record = gate_eval.run_pair(case, 1, lambda: _TripStub(readings), probe_pages=True)
    assert record["agree"] is True
    assert record["stopped"] is False
    assert record["reached"] == 0
    assert record["rotation"] == []
    assert [k for k in record["case"]] == ["sample", "variant", "receipt_file",
                                           "cert_file"]


def test_gate_execute_trips_single_page_pair(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    cases = gate_eval.load_trip_cases(TRIPS)
    case = _enriched("T4_paris_pharmacy", "receipt", None, "clean")
    assert len(case["images"]) == 1
    readings = [_reading_for(cases["T4_paris_pharmacy"], "receipt", None)
                for _ in range(2)]
    record = gate_eval.run_pair(case, 1, lambda: _TripStub(readings), probe_pages=True)
    assert record["agree"] is True
    assert record["reached"] == 0


def test_trips_check_plan_totals():
    summary = trips_check.plan()
    assert len(summary["cases"]) == 6
    rows = {r["id"]: r for r in summary["cases"]}
    # every trip reaches the model now; T4 stops after its reads (no cert)
    two = 2 * BASE_EST + 2 * PROBE_EST + trips_check.CONSISTENCY_EST
    three = 6 * BASE_EST + 3 * PROBE_EST + trips_check.CONSISTENCY_EST
    t4 = 2 * BASE_EST + PROBE_EST
    assert rows["T4_paris_pharmacy"]["estimate"] == (round(t4, 4), round(t4, 4))
    for cid in ("T2_danang_scooter", "T3_setagaya_fever", "T6_guam_dental"):
        assert rows[cid]["live"] is True
        assert rows[cid]["missing_facts"] == []
        assert rows[cid]["eligibility"] == ["traveller_abroad"]
        assert rows[cid]["estimate"] == (round(two, 4),
                                         round(two + 2 * REREAD_EST, 4))
    for cid in ("T1_bangkok_food_poisoning", "T5_honolulu_urgent"):
        assert rows[cid]["live"] is True
        assert rows[cid]["missing_facts"] == []
        assert rows[cid]["estimate"][0] == round(three, 4)
    lo, hi = summary["estimate"]
    two_lo, two_hi = round(two, 4), round(two + 2 * REREAD_EST, 4)
    three_lo = round(three, 4)
    three_hi = round(three + 4 * REREAD_EST, 4)  # T1/T5: 2 bills x2 sides
    t4_lo = round(t4, 4)
    assert lo == round(3 * two_lo + 2 * three_lo + t4_lo, 4)
    assert hi == round(3 * two_hi + 2 * three_hi + t4_lo, 4)
    try:
        trips_check.plan(["T9_nope"])
    except ValueError as exc:
        assert "T9_nope" in str(exc)
    else:
        raise AssertionError("unknown case must raise")


def test_trips_check_plan_text(capsys):
    assert main(["trips-check"]) == 0
    out = capsys.readouterr().out
    for cid in IDS:
        assert cid in out
    assert "Stopped before any API call" in out
    assert main(["trips-check", "--cases", "T4_paris_pharmacy"]) == 0
    out = capsys.readouterr().out
    assert "T4_paris_pharmacy" in out and "T2_danang_scooter" not in out
    assert main(["trips-check", "--cases", "T9_nope"]) == 2
    assert "T9_nope" in capsys.readouterr().err


def test_trips_check_unrecorded_photos_stop_at_probe():
    # Trips photos have no recordings: replay probes miss, so every trip
    # stops at the rotation probe (C4) with no live call and no spend.
    for cid in ("T1_bangkok_food_poisoning", "T4_paris_pharmacy",
                "T5_honolulu_urgent"):
        record = trips_check.run_case(cid)
        assert record["status"] == 200
        assert record["badge"] == "needs_manual_check"
        assert "rotation" in record["title"].lower()
        assert record["cost_usd"] == 0.0


def test_trips_check_two_image_trip_stops_cleanly(monkeypatch):
    from claimlens import serve

    cases = gate_eval.load_trip_cases(TRIPS)
    readings = [_reading_for(cases["T2_danang_scooter"], "receipt",
                             "medical_certificate") for _ in range(2)]
    monkeypatch.setattr(serve, "live_provider", lambda: _TripStub(readings))
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    record = trips_check.run_case("T2_danang_scooter")
    assert record["status"] == 200
    assert record["badge"] == "engine_unreachable"
    assert len(record["questions"]) == 1


def test_trips_check_judge():
    expected = {"status": 200, "badge": "engine_unreachable"}
    assert trips_check.judge({"status": 200, "badge": "engine_unreachable"},
                             expected)["verdict"] == "PASS"
    earlier = trips_check.judge({"status": 200, "badge": "blocked"}, expected)
    assert earlier["verdict"] == "PASS (earlier stop)"
    decided = trips_check.judge({"status": 200, "badge": "PAID"}, expected)
    assert decided["verdict"] == "FAIL"
    wrong_status = trips_check.judge({"status": 400, "error": "x"}, expected)
    assert wrong_status["verdict"] == "FAIL"
    refused = {"status": 400, "reason": "Upload 1 to 6"}
    ok = trips_check.judge({"status": 400, "error": "Upload 1 to 6 images: "
                            "up to 5 receipts and 1 certificate."}, refused)
    assert ok["verdict"] == "PASS"
    bad = trips_check.judge({"status": 400, "error": "boom"}, refused)
    assert bad["verdict"] == "FAIL"


def test_trips_check_execute_writes_report(tmp_path, monkeypatch):
    from claimlens import serve

    cases = gate_eval.load_trip_cases(TRIPS)
    t4_only = _reading_for(cases["T4_paris_pharmacy"], "receipt", None)
    t4_only["documents"] = t4_only["documents"][:1]  # pharmacy ticket, no cert
    readings = [copy.deepcopy(t4_only) for _ in range(2)]
    readings += [_reading_for(cases["T2_danang_scooter"], "receipt",
                              "medical_certificate") for _ in range(2)]
    monkeypatch.setattr(serve, "live_provider", lambda: _TripStub(readings))
    monkeypatch.setattr(serve, "neo4j_up", lambda: False)
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    out = tmp_path / "out"
    results = trips_check.execute(["T4_paris_pharmacy", "T2_danang_scooter"],
                                  1.0, out)
    assert results["aborted"] is False
    assert [c["verdict"] for c in results["cases"]] == ["PASS", "PASS"]
    assert results["spent"] > 0  # the T2 run made stub calls
    assert Path(results["path"]).is_file()
    text = trips_check.format_results(results)
    assert "T4_paris_pharmacy: PASS" in text
    assert "T2_danang_scooter: PASS" in text


def test_trips_check_execute_aborts_past_max_cost(tmp_path, monkeypatch):
    from claimlens import serve

    cases = gate_eval.load_trip_cases(TRIPS)
    readings = [_reading_for(cases["T2_danang_scooter"], "receipt",
                             "medical_certificate") for _ in range(2)]
    monkeypatch.setattr(serve, "live_provider", lambda: _TripStub(readings))
    monkeypatch.setenv("CLAIMLENS_CACHE_DIR", str(tmp_path / "cache"))
    results = trips_check.execute(["T2_danang_scooter"], -1.0, tmp_path / "out")
    assert results["aborted"] is True
    assert len(results["cases"]) == 1


def test_scenario_uploads_use_photo_images():
    case = gate_eval.load_trip_cases(TRIPS)["T1_bangkok_food_poisoning"]
    paths = trips_check.scenario_uploads(case, TRIPS / "T1_bangkok_food_poisoning")
    assert [p.name for p in paths] == ["receipt_er_photo.jpg",
                                       "receipt_pharm_photo.jpg",
                                       "medical_certificate_photo.jpg"]
    for path in paths:
        blob = path.read_bytes()
        assert blob[:2] == b"\xff\xd8"  # real JPEG bytes through route_post
        base64.b64encode(blob)  # encodable for the upload body
