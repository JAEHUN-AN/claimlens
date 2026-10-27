"""Demo page tests: offline export with all three scenes."""

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
    assert ko_clip["confirmations"][0]["question"].startswith("I heard 20 October")
    for entry in timeline["entries"]:
        for seg in entry.get("segments", []):
            assert "None" not in seg.get("t", "") + seg.get("n", "")


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
