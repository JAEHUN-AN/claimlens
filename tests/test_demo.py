"""Demo page tests: offline export with all three scenes."""

import json
import re

from claimlens.demo import export_demo


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
    raw = re.search(r'<script id="demo-data"[^>]*>(.*?)</script>', text, re.DOTALL)[1]
    payload = json.loads(raw)
    assert [s["id"] for s in payload["scenes"]] == [
        "A_niseko_wrist",
        "S2_seoul_worker_bronchitis",
        "S3_us_tourist_hip_fracture",
    ]
    assert payload["scenes"][0]["card"]["decision"] == "PAID"
    assert payload["scenes"][1]["eligibility"]["outcome"] == "nhi_member"
    assert payload["scenes"][2]["pack"] is not None
