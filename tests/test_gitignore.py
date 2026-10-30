"""Repo hygiene: runtime-only paths must stay out of git (S6)."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_gitignore_blocks_nested_live_dirs():
    """S6: **/live/ ignores runtime results at any depth."""
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "**/live/" in gitignore.splitlines()
    proc = subprocess.run(
        ["git", "-c", "safe.directory=*", "check-ignore",
         "cache/hard/live/newfile.json"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, "nested live/ path is not ignored"
