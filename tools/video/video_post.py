"""Post-production for the v3 recorders: rush, mux, frame check.

The record path saves the measured actuals next to the webm; --post-only
redoes everything after the browser from those files, with no browser
and no live call. Failures print the full ffmpeg command and stderr.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import video_lib as V
import video_sound as VS

__all__ = [
    "actuals_from_timeline",
    "load_actuals",
    "resolve_post_inputs",
    "run_post",
    "save_actuals",
]

TIME_RE = re.compile(r"(\d+):(\d+):([\d.]+)")


def save_actuals(path: Path, actuals: list[tuple[str, float, float]], lead: float,
                 planned_total: float) -> None:
    """Persist the measured recording for --post-only reruns."""
    data = {
        "lead": lead,
        "planned_total": planned_total,
        "actuals": [{"seg": sid, "start": s, "end": e} for sid, s, e in actuals],
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_actuals(path: Path) -> tuple[list[tuple[str, float, float]], float, float]:
    """Load a saved measurement. Returns (actuals, lead, planned_total)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        actuals = [(row["seg"], float(row["start"]), float(row["end"])) for row in data["actuals"]]
        return actuals, float(data["lead"]), float(data["planned_total"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"bad actuals file {path}: {exc}") from exc


def _parse_time(text: str) -> float:
    match = TIME_RE.fullmatch(text.strip())
    if not match:
        raise ValueError(f"bad timestamp {text!r}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def actuals_from_timeline(timeline_path: Path) -> list[tuple[str, float, float]]:
    """Recover segment boundaries from a timeline file (legacy rescue).

    Only the recorded-actuals section parses; stops at the final-cut
    appendix. Anything malformed raises instead of guessing.
    """
    actuals = []
    for line in timeline_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            break
        if not line.strip():
            continue
        head, sep, rest = line.partition(" --> ")
        if not sep:
            raise ValueError(f"bad timeline line: {line}")
        tokens = rest.split()
        if len(tokens) < 2:
            raise ValueError(f"bad timeline line: {line}")
        actuals.append((tokens[1], _parse_time(head), _parse_time(tokens[0])))
    if not actuals:
        raise ValueError(f"no segments in {timeline_path}")
    return actuals


def _check_ids(board: dict, actuals: list[tuple[str, float, float]]) -> None:
    wanted = [seg["id"] for seg in board.get("segments", [])]
    got = [sid for sid, _, _ in actuals]
    if got != wanted:
        raise ValueError(f"actuals cover {got}, storyboard wants {wanted}")


def resolve_post_inputs(board: dict, out_dir: Path, webm_name: str, actuals_name: str,
                        timeline_name: str, prefix: str, webm_arg: str | None,
                        actuals_arg: str | None, lead_arg: float | None):
    """Locate webm + actuals + lead for --post-only. Returns (webm, actuals, lead).

    Prefers the saved actuals file; without it, recovers boundaries from
    the timeline and estimates the lead by finding the opening card in
    the webm (warns: good to ~1 s). Explicit --actuals/--lead win.
    """
    webm = Path(webm_arg) if webm_arg else out_dir / webm_name
    if not webm.is_file():
        raise RuntimeError(f"webm not found: {webm}")
    lead = lead_arg
    actuals: list[tuple[str, float, float]] | None = None
    if actuals_arg:
        actuals, file_lead, _ = load_actuals(Path(actuals_arg))
        if lead is None:
            lead = file_lead
    else:
        default = out_dir / actuals_name
        if default.is_file():
            actuals, file_lead, _ = load_actuals(default)
            if lead is None:
                lead = file_lead
    if actuals is None:
        print("no saved actuals; recovering from the timeline + frame search", file=sys.stderr)
        actuals = actuals_from_timeline(out_dir / timeline_name)
        if lead is None:
            first = board["segments"][0]
            ref = out_dir / f"{prefix}{first['id']}_mid.png"
            if not ref.is_file():
                raise RuntimeError(f"lead rescue needs the midpoint PNG: {ref}")
            lead = VS.content_lead(webm, ref, first["duration"] / 2)
            print(f"estimated lead {lead:.1f}s from the opening card (good to ~1 s)",
                  file=sys.stderr)
    _check_ids(board, actuals)
    if lead is None:
        raise RuntimeError("cannot determine the lead; pass --lead SECONDS")
    return webm, actuals, lead


def run_post(board: dict, out_dir: Path, webm: Path, actuals: list[tuple[str, float, float]],
             lead: float, total: float | None, music: Path | None, prefix: str,
             timeline_name: str, limit: float, voice=None) -> int:
    """Rush, mux, and frame-check a recorded webm. Returns an exit code.

    total=None keeps the exact cut length (vertical); otherwise -t total.
    Every failure prints the full command and stderr.
    """
    sped_path = webm.with_name(webm.stem + "_sped.mp4")
    try:
        video_src, spans, final_len = V.apply_rush(board, actuals, lead, limit, webm, sped_path)
    except (subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        _show("rush", exc)
        return 2
    V.append_final_cut(out_dir / timeline_name, board, actuals, lead, spans)
    if V.final_times(actuals, lead, spans)[-1][2] > limit + 0.05:
        print(f"final cut exceeds {limit:g} s; failing instead of cutting the ending",
              file=sys.stderr)
        return 2
    if not VS.have_ffmpeg():
        print("ffmpeg not found; .webm kept, .mp4 skipped", file=sys.stderr)
        return 2
    mp4 = webm.with_name(webm.stem + ".mp4")
    keep = total if total is not None else final_len - lead
    try:
        VS.mux_sound(video_src, mp4, keep, voice=voice, music=music, lead=lead)
    except subprocess.CalledProcessError as exc:
        _show("mux", exc)
        return 2
    print(f"wrote {mp4}")
    try:
        diff = V.check_first_frame(mp4, board, out_dir, prefix)
    except subprocess.CalledProcessError as exc:
        _show("frame check", exc)
        return 2
    except RuntimeError as exc:
        print(f"frame check failed: {exc}", file=sys.stderr)
        return 2
    print(f"frame check OK (diff {diff:.1f})")
    return 0


def _show(stage: str, exc: subprocess.CalledProcessError) -> None:
    print(f"{stage} failed:", file=sys.stderr)
    if getattr(exc, "cmd", None):
        print(f"command: {exc.cmd}", file=sys.stderr)
    print(f"stderr:\n{getattr(exc, 'stderr', None) or exc}", file=sys.stderr)
