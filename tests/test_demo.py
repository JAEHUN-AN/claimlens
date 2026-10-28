"""Demo page tests: offline export with all six scenes."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from claimlens.demo import export_demo


def _node_path(path: Path) -> str:
    return str(path).removeprefix("\\\\?\\")


def test_demo_exports_three_offline_scenes(tmp_path, monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    dst = export_demo(tmp_path / "demo.html")
    text = dst.read_text(encoding="utf-8")
    assert "A_niseko_wrist" in text
    assert "S2_seoul_worker_bronchitis" in text
    assert "S3_us_tourist_hip_fracture" in text
    assert "pre-existing open-source engine, pinned" in text
    assert "We do not have your policy, so this is not a coverage decision." in text
    assert "matches the engine" in text
    assert "http://-onwards" not in text and "https://" not in text
    assert "# Claim decision" not in text
    assert "<iframe" not in text
    raw = re.search(r'<script id="demo-data"[^>]*>(.*?)</script>', text, re.DOTALL)[1]
    payload = json.loads(raw)
    assert [s["id"] for s in payload["scenes"]] == [
        "A_niseko_wrist",
        "S2_seoul_worker_bronchitis",
        "S3_us_tourist_hip_fracture",
        "agent_s2_hidden_copay",
        "voice_factory_fall",
        "mismatch_s2r_s3c",
    ]
    assert payload["scenes"][0]["card"]["decision"] == "PAID"
    assert payload["scenes"][0]["card"]["steps"]
    assert payload["scenes"][0]["card"]["clauses"]
    assert payload["scenes"][1]["eligibility"]["outcome"] == "nhi_member"
    assert payload["scenes"][1]["card"]["deductible"]["match"] is True
    assert payload["scenes"][2]["pack"] is not None
    assert len(payload["scenes"][2]["pack"]["items"]) == 12
    assert payload["scenes"][2]["pack"]["total_krw"] == {
        "v": "15,000,000",
        "prov": "s3-pack-total",
    }
    assert "pack_vi" not in payload["scenes"][2]
    recovery = payload["scenes"][2]["recovery"]
    assert recovery["before"]["lines"] == {"v": "0/12", "prov": "s3-rec-lines-before"}
    assert recovery["after"]["lines"] == {"v": "12/12", "prov": "s3-rec-lines-after"}
    assert recovery["corrected"] == ["line_items"]
    assert recovery["status"] == "verified"
    assert recovery["image"]["src"].endswith("receipt_clean.png")
    first_images = payload["scenes"][0]["images"]
    assert set(first_images[0]) == {"src", "caption"}
    assert "masked copy" in payload["scenes"][1]["images"][0]["caption"]
    assert "masked copy" in payload["scenes"][2]["images"][1]["caption"]
    timeline = payload["scenes"][3]["timeline"]
    assert timeline["outcome"]["decision"] == "PARTIAL"
    assert timeline["outcome"]["amount_krw"] == 22500
    kinds = [e["kind"] for e in timeline["entries"]]
    assert kinds.count("question") == 1
    assert kinds[-1] == "final"
    voice = payload["scenes"][4]
    assert voice["eligibility"]["outcome"] == "work_injury"
    assert voice["next_step"] == "industrial accident compensation insurance first"
    assert [c["lang"] for c in voice["clips"]] == ["en", "ko"]
    assert all(c["transcript"] and c["audio"].endswith(".wav") for c in voice["clips"])
    ko_clip = voice["clips"][1]
    assert ko_clip["to_confirm"] == ["incident_date", "visa"]
    assert ko_clip["confirmations"][0]["question"] == "10월 20일로 들었습니다 — 맞나요?"
    assert ko_clip["confirmations"][1]["question"] == "비자 E-9로 들었습니다 — 맞나요?"
    for entry in timeline["entries"]:
        for seg in entry.get("segments", []):
            assert "None" not in seg.get("t", "") + seg.get("n", "")
    verification = timeline["verification"]
    assert verification["trace_guards"] == [
        {"step": 7, "tool": "adjudicate", "verdict": "pass", "rule": "", "feedback": ""}
    ]
    walkthrough = verification["walkthrough"]
    assert walkthrough["refusal"]["rule"] == "receipt_checks"
    assert walkthrough["fix"]["decision"] == "PARTIAL"
    assert walkthrough["fix"]["amount_krw"] == 22500
    assert walkthrough["handoff"]["rule_fired"] == "receipt_checks"
    assert walkthrough["signoff"]["signed"] == "approved"
    mismatch = payload["scenes"][5]["mismatch"]
    assert mismatch["bundle"] == "S2r-S3c"
    assert mismatch["stopped"] is True
    ruled = [f for f in mismatch["findings"] if f["layer"] == "rule"]
    assert sorted(f["kind"] for f in ruled if f["severity"] == "blocker") == [
        "patient_name",
        "visit_date",
        "visit_type",
    ]
    assert all(f["quote_receipt"] and f["quote_cert"] and f["reason"] for f in mismatch["findings"])
    assert all(f["question"] and f["why_needed"] for f in ruled if f["severity"] == "blocker")
    flow = payload["flow"]["examples"]
    assert [e["id"] for e in flow] == [
        "A_niseko_wrist",
        "S2_seoul_worker_bronchitis",
        "S3_us_tourist_hip_fracture",
        "agent_s2_hidden_copay",
        "voice_factory_fall",
    ]
    for example in flow:
        assert len(example["steps"]) >= 3
        assert all(s["label"] and s["detail"] and s["meta"] for s in example["steps"])
        assert example["result"]["badge"]
    assert [s["key"] for s in flow[3]["steps"]].count("ask_user") == 1
    assert flow[4]["result"]["badge"] == "work_injury"
    evaluation = payload["flow"]["eval"]
    assert [r["sample"] for r in evaluation["rows"]] == ["A", "B", "C", "S2", "S3"]
    assert (evaluation["rows"][0]["lines"], evaluation["rows"][0]["pii"]) == ("6/6", "4/4")
    b, c, s2 = evaluation["rows"][1], evaluation["rows"][2], evaluation["rows"][3]
    assert (b["lines"], b["diags"], b["checks"], b["pii"]) == ("7/7", "2/2", "n/a", "4/4")
    assert (c["lines"], c["diags"], c["checks"], c["pii"]) == ("7/7", "2/2", "n/a", "4/4")
    assert (s2["lines"], s2["diags"], s2["checks"], s2["pii"]) == ("5/5", "1/1", "10/10 pass", "2/2")
    s3 = evaluation["rows"][4]
    assert (s3["total"], s3["lines"], s3["diags"], s3["checks"], s3["pii"]) == (
        "ok",
        "12/12",
        "1/1",
        "10/10 pass",
        "3/4",
    )
    assert evaluation["open_line"] == (
        "Open weights match hosted on A/B; differ on C total, S2 checks, S3 checks."
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_demo_renders_in_node_harness(tmp_path, monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    dst = export_demo(tmp_path / "demo.html")
    harness = Path(__file__).with_name("demo_smoke.mjs")
    proc = subprocess.run(
        ["node", _node_path(harness), _node_path(dst)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "demo smoke: OK" in proc.stdout
