"""Storyboard dry run for the demo video (no browser needed)."""

import json
import subprocess
import sys
from pathlib import Path


def test_storyboard_dry_run():
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "scripts/record_video.py", "--dry-run"],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY RUN: OK" in proc.stdout
    assert "total 180s / 180s" in proc.stdout


def test_storyboard_v2_dry_run():
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "scripts/record_video_v2.py", "--dry-run"],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY RUN: OK" in proc.stdout
    assert "total 180s / 180s" in proc.stdout


def test_storyboard_v3_dry_run():
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "scripts/record_video_v3.py", "--dry-run"],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY RUN: OK" in proc.stdout
    assert "total 180s / 180s" in proc.stdout


def test_vertical_v3_dry_run():
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "scripts/record_vertical_v3.py", "--dry-run"],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY RUN: OK" in proc.stdout
    assert "final cut 45s / 45s" in proc.stdout


def test_v3_dry_run_catches_missing_drop_file(tmp_path):
    root = Path(__file__).resolve().parent.parent
    storyboard = json.loads((root / "docs" / "video" / "storyboard-v3.json").read_text(encoding="utf-8"))
    for seg in storyboard["segments"]:
        for act in seg.get("actions", []):
            if act.get("op") == "dropfiles":
                act["files"] = ["samples/live/nope.jpg"]
    bad = tmp_path / "bad_v3.json"
    bad.write_text(json.dumps(storyboard), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "scripts/record_video_v3.py", "--dry-run", "--storyboard", str(bad)],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 1
    assert "drop file missing" in proc.stdout


def test_vertical_dry_run():
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "scripts/record_vertical.py", "--dry-run"],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY RUN: OK" in proc.stdout
    assert "total 45s / 45s" in proc.stdout


def test_storyboard_v2_dry_run_catches_unknown_card(tmp_path):
    root = Path(__file__).resolve().parent.parent
    storyboard = json.loads((root / "docs" / "video" / "storyboard-v2.json").read_text(encoding="utf-8"))
    storyboard["segments"][0]["page"] = "card:nope"
    bad = tmp_path / "bad_v2.json"
    bad.write_text(json.dumps(storyboard), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "scripts/record_video_v2.py", "--dry-run", "--storyboard", str(bad)],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 1
    assert "unknown card id" in proc.stdout


def test_vertical_dry_run_catches_long_caption(tmp_path):
    root = Path(__file__).resolve().parent.parent
    storyboard = json.loads((root / "docs" / "video" / "vertical.json").read_text(encoding="utf-8"))
    storyboard["segments"][0]["caption"] = "x" * 45
    bad = tmp_path / "bad_vertical.json"
    bad.write_text(json.dumps(storyboard), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "scripts/record_vertical.py", "--dry-run", "--storyboard", str(bad)],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 1
    assert "caption over 44 chars" in proc.stdout


def test_storyboard_dry_run_catches_ambiguous_nav(tmp_path):
    root = Path(__file__).resolve().parent.parent
    storyboard = json.loads((root / "docs" / "video" / "storyboard.json").read_text(encoding="utf-8"))
    for seg in storyboard["segments"]:
        for act in seg.get("actions", []):
            if act.get("selector", "").endswith('Scene A —")'):
                act["selector"] = '#scenes button:has-text("Scene A")'
    bad = tmp_path / "bad_storyboard.json"
    bad.write_text(json.dumps(storyboard), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "scripts/record_video.py", "--dry-run", "--storyboard", str(bad)],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 1
    assert "matches 2 nav buttons" in proc.stdout
