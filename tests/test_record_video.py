"""Storyboard dry run for the demo video (no browser needed)."""

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
