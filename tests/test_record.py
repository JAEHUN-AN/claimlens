"""Entry-point dry runs for the demo video (no browser needed)."""

import json
import subprocess
import sys
from pathlib import Path

ENTRY = ["tools/video/record.py"]


def _run(root: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *ENTRY, *args],
        check=False,
        cwd=cwd or root,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_main_dry_run():
    root = Path(__file__).resolve().parent.parent
    proc = _run(root, "main", "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY RUN: OK" in proc.stdout
    assert "total 180s / 180s" in proc.stdout


def test_vertical_dry_run():
    root = Path(__file__).resolve().parent.parent
    proc = _run(root, "vertical", "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY RUN: OK" in proc.stdout
    assert "final cut 45s / 45s" in proc.stdout


def test_entry_rejects_unknown_cut():
    root = Path(__file__).resolve().parent.parent
    proc = _run(root, "v2", "--dry-run")
    assert proc.returncode == 2
    assert "usage: record.py main|vertical" in proc.stderr


def test_main_dry_run_catches_missing_drop_file(tmp_path):
    root = Path(__file__).resolve().parent.parent
    board_path = root / "tools" / "video" / "storyboard-main.json"
    storyboard = json.loads(board_path.read_text(encoding="utf-8"))
    for seg in storyboard["segments"]:
        for act in seg.get("actions", []):
            if act.get("op") == "dropfiles":
                act["files"] = ["samples/live/nope.jpg"]
    bad = tmp_path / "bad_main.json"
    bad.write_text(json.dumps(storyboard), encoding="utf-8")
    proc = _run(root, "main", "--dry-run", "--storyboard", str(bad))
    assert proc.returncode == 1
    assert "drop file missing" in proc.stdout


def test_post_only_fails_cleanly_without_webm(tmp_path):
    root = Path(__file__).resolve().parent.parent
    proc = _run(
        root, "main", "--post-only", "--out", str(tmp_path),
        cwd=Path(str(root).removeprefix("\\\\?\\")),
    )
    assert proc.returncode == 2
    assert "webm not found" in proc.stderr
