"""Storyboard captions v5 (63): short on-screen keywords, speech carries detail.

Caption templates live here (verbatim owner draft); the N slots come
from claimlens.headline at refresh time. Run after `claimlens headline`,
which still rewrites the eval caption in the old long form:

    uv run python tools/video/captions.py refresh
    uv run python tools/video/captions.py --check   # exit 1 when stale

Narrations (today's long captions) live only in the storyboards, except
the gate narration, which refresh rebuilds as eval caption + trips line.
Chapter cards and the vertical cut keep static text.
"""

import json
import re
import sys
from pathlib import Path

__all__ = [
    "CAPTIONS",
    "check",
    "main",
    "numbers",
    "refresh",
]

ROOT = Path(__file__).resolve().parent.parent.parent
MAIN_BOARD = ROOT / "tools" / "video" / "storyboard-main.json"

CAPTIONS = {
    "thesis": "AI reads. Code counts. People decide.",
    "why": "\u20a9251.2B unclaimed (2022, est.) \u00b7 2.01M foreign patients (2025)",
    "before_after": "By hand: 30+ min (est.) \u2192 ClaimLens: ~{n} s (measured)",
    "s2flow": "Every cell read \u2192 re-added in code",
    "prov": "Every number shows its source",
    "agent": "Something missing? It asks \u2014 never guesses",
    "score": "Agent scorecard {a}/{b}",
    "s3": "No policy \u2192 no decision, a claim pack",
    "voice": "Spoken dates: confirmed, not trusted",
    "live": "LIVE \u00b7 new photos \u00b7 real Muse Spark call",
    "mismatch": "Documents disagree \u2192 a question",
    "verify": "Checks the agent can't skip",
    "phone": "Same proof on your phone",
    "tools": "6 Meta tools, each measured",
    "builtvs": "Built here \u00b7 engine pre-existing, pinned",
    "gate": "Wrong amounts: {old} (old single read) \u2192 {live} (live gate)",
    "sceneA": "The other way: a Korean skier in Japan",
    "closing": "Try it: jaehun-an.github.io/claimlens \u00b7 github.com/JAEHUN-AN/claimlens",
}


def numbers(root: Path = ROOT) -> dict[str, str]:
    """Caption numbers from headline data. Raises when data is missing."""
    from claimlens import headline

    n = headline.after_n(root)
    agent = headline.agent_line(root)
    legacy = headline.legacy_line(root)
    gate = headline.gate_line(root)
    if not n or not agent or not legacy or not gate:
        raise ValueError("headline data missing for caption numbers")
    score = re.search(r"Agent scorecard: (\d+)/(\d+)", agent["en"])
    old = re.search(r"(\d+) wrong amounts left", legacy["en"])
    live = re.search(r"(\d+) wrong amounts left", gate["en"])
    if not score or not old or not live:
        raise ValueError("headline wording changed; caption parse failed")
    return {"n": n, "a": score.group(1), "b": score.group(2),
            "old": old.group(1), "live": live.group(1)}


def _wanted(root: Path) -> dict[str, tuple[str, str | None]]:
    """Segment id -> (caption, narration-or-None-to-keep) from templates + data."""

    nums = numbers(root)
    wanted = {sid: (template.format(**nums), None)
              for sid, template in CAPTIONS.items()}
    caption, _ = wanted["gate"]
    wanted["gate"] = (caption, gate_narration(root, nums))
    caption, _ = wanted["before_after"]
    wanted["before_after"] = (caption, BEFORE_AFTER_NARRATION.format(**nums))
    return wanted


# Owner-approved sentence (backlog Round 10) + the measured side, spoken.
BEFORE_AFTER_NARRATION = (
    "By hand, this takes 30+ minutes per claim, by the builder's estimate. "
    "ClaimLens takes about {n} seconds, measured.")


def gate_narration(root: Path, nums: dict[str, str]) -> str:
    """Short spoken gate line: single read vs live gate, then the real trips.

    Counts come from headline.trips_line; a wording change raises instead of
    guessing. The full trips sentence stays on the first screen.
    """
    from claimlens import headline

    text = (f"A single read on the old pipeline let {nums['old']} wrong amounts "
            f"through; the live gate let {nums['live']}.")
    trips = headline.trips_line(root)
    if trips is None:
        return text
    line = trips["en"]
    decided = re.search(r"(\d+) of (\d+) decided", line)
    held = re.search(r"; ([^;]*) correctly not decided", line)
    stopped = re.search(r"; ([^;]*) stopped for a person", line)
    if not decided:
        raise ValueError("trips line wording changed; gate narration parse failed")
    exact = "each paid amount matches" in line
    parts = [f"{decided.group(1)} decided" + (" at exactly the expected amounts" if exact else "")]
    if held:
        parts.append(f"{len(re.findall(r'T\d+', held.group(1)))} correctly held back")
    if stopped:
        parts.append(f"{len(re.findall(r'T\d+', stopped.group(1)))} stopped for a person")
    return text + " Real trips: " + ", ".join(parts) + "."


def refresh(root: Path = ROOT) -> bool:
    """Rewrite templated captions (+ eval narration). True when changed."""
    path = root / "tools" / "video" / "storyboard-main.json"
    raw = path.read_bytes()
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    board = json.loads(raw.decode("utf-8"))
    wanted = _wanted(root)
    changed = False
    for seg in board["segments"]:
        if seg["id"] not in wanted:
            continue
        caption, narration = wanted[seg["id"]]
        if seg.get("caption") != caption:
            seg["caption"] = caption
            changed = True
        if narration is not None and seg.get("narration") != narration:
            seg["narration"] = narration
            changed = True
    if changed:
        text = json.dumps(board, indent=2, ensure_ascii=False)
        path.write_bytes(text.replace("\n", newline.decode()).encode("utf-8")
                         + newline)
    return changed


def check(root: Path = ROOT) -> list[str]:
    """Staleness errors without writing. Empty means fresh."""
    path = root / "tools" / "video" / "storyboard-main.json"
    board = json.loads(path.read_text(encoding="utf-8"))
    wanted = _wanted(root)
    errors = []
    for seg in board["segments"]:
        if seg["id"] not in wanted:
            continue
        caption, narration = wanted[seg["id"]]
        if seg.get("caption") != caption:
            errors.append(f"{seg['id']}: caption stale")
        if narration is not None and seg.get("narration") != narration:
            errors.append(f"{seg['id']}: narration stale")
    return errors


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--check"]:
        errors = check()
        for error in errors:
            print(error)
        return 1 if errors else 0
    if args in ([], ["refresh"]):
        print("refreshed" if refresh() else "fresh")
        return 0
    print("usage: captions.py [refresh|--check]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
