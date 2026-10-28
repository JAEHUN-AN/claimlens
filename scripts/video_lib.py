"""Shared helpers for the demo-video recorders (v1, v2, vertical).

Validation and planning live here; the browser runner, shot pages and
ffmpeg sound are sibling modules re-exported for the record scripts.
"""

import json
import re
from pathlib import Path

from video_run import (
    Clock,
    clean_out,
    drop_payload,
    fmt_time,
    goto,
    live_key_present,
    locate,
    run_action,
    run_segments,
    serve,
    start_live_server,
    uses_live,
)
from video_shots import SHOTS, build_shots
from video_sound import (
    check_first_frame,
    content_lead,
    extract_frame,
    ffmpeg_bin,
    find_font,
    have_ffmpeg,
    mean_frame_diff,
    mux_sound,
    speed_filter,
    speed_spans,
    voice_at,
)

__all__ = [
    "BASE_HOOKS",
    "CARD_IDS",
    "FX_HOOKS",
    "OPS",
    "SHOTS",
    "Clock",
    "append_final_cut",
    "apply_rush",
    "build_shots",
    "check_assets",
    "check_first_frame",
    "clean_out",
    "content_lead",
    "drop_payload",
    "effective_total",
    "extract_frame",
    "ffmpeg_bin",
    "final_times",
    "find_font",
    "fmt_time",
    "goto",
    "have_ffmpeg",
    "live_key_present",
    "locate",
    "mean_frame_diff",
    "mux_sound",
    "nav_texts",
    "overlay_fx_js",
    "overlay_js",
    "page_texts_for",
    "pick_rush",
    "print_plan",
    "run_action",
    "run_segments",
    "serve",
    "speed_filter",
    "speed_spans",
    "start_live_server",
    "tokens",
    "uses_live",
    "validate",
    "voice_at",
]

CARD_IDS = ("cold", "ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "meta", "vhook", "vmeta", "vlink",
            "thesis")
OPS = ("click", "move", "scroll_to", "wait_for", "hold", "goto", "zoom", "unzoom", "dropfiles",
       "press")
BASE_HOOKS = ("window.__cap", "window.__dot", "window.__pulse", "window.__place", "#vcap", "#vdot")
FX_HOOKS = ("window.__zoom", "window.__unzoom", "window.__zoomFit",
            "vzoom", "vpop", "vplink", "vhl")
VIDEO_DIR = Path("docs/video")


def overlay_js(root: Path, font_px: int = 23) -> str:
    text = (root / VIDEO_DIR / "overlay.js").read_text(encoding="utf-8")
    return text.replace("%%FONT%%", str(font_px))


def overlay_fx_js(root: Path) -> str:
    return (root / VIDEO_DIR / "overlay_fx.js").read_text(encoding="utf-8")


def tokens(selector: str) -> list[str]:
    """Queryable tokens of a Playwright selector: ids, classes, attrs, texts."""
    toks: list[str] = []
    toks += re.findall(r"#([\w-]+)", selector)
    toks += re.findall(r"\.([\w-]+)", selector)
    for match in re.finditer(r"\[([\w-]+)(?:=\"([^\"]*)\"|='([^']*)')?\]", selector):
        toks.append(match.group(1))
        toks += [g for g in (match.group(2), match.group(3)) if g]
    for match in re.finditer(r":has-text\((\"([^\"]*)\"|'([^']*)')\)", selector):
        toks += [g for g in (match.group(2), match.group(3)) if g]
    return toks


def nav_texts(demo_text: str) -> list[str]:
    match = re.search(r'<script id="demo-data"[^>]*>(.*?)</script>', demo_text, re.DOTALL)
    payload = json.loads(match.group(1))
    return ["Guided flow"] + [s["title"] for s in payload["scenes"]]


MULTI = ("fstep", "totag", "plink", "pill", "audio")


def validate(root: Path, board: dict, texts: dict[str, str], caption_max: int) -> list[str]:
    """Storyboard checks that need no browser. Returns error strings."""
    errors: list[str] = []
    segments = board.get("segments", [])
    for seg in segments:
        if not seg.get("caption"):
            errors.append(f"{seg.get('id')}: empty caption")
        elif len(seg["caption"]) > caption_max:
            errors.append(f"{seg.get('id')}: caption over {caption_max} chars")
        if seg.get("duration", 0) <= 0:
            errors.append(f"{seg.get('id')}: bad duration")
        speed = seg.get("speed")
        if speed is not None and (not isinstance(speed, (int, float)) or speed <= 1):
            errors.append(f"{seg.get('id')}: bad speed {speed!r}")
        rush = seg.get("rush")
        if rush is not None:
            first = rush.get("first", 0) if isinstance(rush, dict) else None
            last = rush.get("last", 0) if isinstance(rush, dict) else None
            ok = (
                isinstance(first, (int, float)) and isinstance(last, (int, float))
                and first >= 0 and last >= 0 and first + last < seg.get("duration", 0)
            )
            if not ok:
                errors.append(f"{seg.get('id')}: bad rush {rush!r}")
        if seg.get("page") not in texts:
            errors.append(f"{seg.get('id')}: unknown page {seg.get('page')!r}")
            continue
        current = seg["page"]
        for act in seg.get("actions", []):
            if act.get("op") not in OPS:
                errors.append(f"{seg['id']}: unknown op {act.get('op')!r}")
                continue
            if act["op"] == "goto":
                if act.get("page") not in texts:
                    errors.append(f"{seg['id']}: goto unknown page {act.get('page')!r}")
                else:
                    current = act["page"]
                continue
            if act["op"] in ("hold", "unzoom"):
                if act["op"] == "hold" and act.get("seconds", 0) <= 0:
                    errors.append(f"{seg['id']}: bad hold")
                continue
            if act["op"] == "press":
                if not act.get("key"):
                    errors.append(f"{seg['id']}: press needs a key")
                continue
            if act["op"] == "dropfiles":
                if not act.get("files"):
                    errors.append(f"{seg['id']}: dropfiles needs files")
                for name in act.get("files", []):
                    if not (root / name).is_file():
                        errors.append(f"{seg['id']}: drop file missing: {name}")
            sel = act.get("selector", "")
            if act.get("frame"):
                for tok in tokens(act["frame"]):
                    if tok not in texts[current]:
                        errors.append(f"{seg['id']}: frame {tok!r} missing on {current}")
                page_text = texts["demo"]
            else:
                page_text = texts[current]
            for tok in tokens(sel):
                if tok not in page_text:
                    errors.append(f"{seg['id']}: {tok!r} missing on {current}")
            if current == "demo" and "#scenes button" in sel and not act.get("frame"):
                for nav_text in re.findall(r':has-text\("([^"]*)"\)', sel):
                    hits = [b for b in nav_texts(texts["demo"]) if nav_text.lower() in b.lower()]
                    if len(hits) != 1:
                        errors.append(f"{seg['id']}: {nav_text!r} matches {len(hits)} nav buttons, want 1")
            lowered = sel.lower()
            if (
                act["op"] in ("click", "move", "scroll_to", "zoom")
                and any(m in lowered for m in MULTI)
                and "nth" not in act
                and "[data-" not in sel
            ):
                errors.append(f"{seg['id']}: {sel!r} may match several nodes, add nth or a data filter")
    return errors


def page_texts_for(root: Path, tmp: Path, extra: dict[str, Path]) -> dict[str, str]:
    """Demo + shot + extra (cards/phone) page texts for validation."""
    shots = build_shots(root, tmp)
    texts = {"demo": (root / "docs" / "demo.html").read_text(encoding="utf-8")}
    texts.update({k: v.read_text(encoding="utf-8") for k, v in shots.items()})
    texts.update({k: v.read_text(encoding="utf-8") for k, v in extra.items()})
    return texts


def check_assets(root: Path, board: dict, texts: dict[str, str]) -> list[str]:
    """Cards/phone pages: local refs exist, no remote URLs, card ids known."""
    errors: list[str] = []
    used = {s["page"] for s in board["segments"]}
    used.update(a["page"] for s in board["segments"] for a in s.get("actions", []) if a.get("op") == "goto")
    for page in used:
        if page.startswith("card:"):
            if page[5:] not in CARD_IDS:
                errors.append(f"unknown card id {page!r}")
        elif page not in texts:
            errors.append(f"unknown page {page!r}")
    for name in ("cards", "phone"):
        if name not in texts:
            continue
        if "https://" in texts[name] or "http://" in texts[name]:
            errors.append(f"{name} page has a remote reference")
        for src in re.findall(r'<img[^>]+src="([^"]+)"', texts[name]):
            if not src.startswith("/") or not (root / src[1:]).exists():
                errors.append(f"{name} image missing: {src}")
    return errors


def effective_total(board: dict) -> float:
    """Final-cut length: sped segments count duration / speed."""
    total = 0.0
    for seg in board.get("segments", []):
        total += seg["duration"] / seg["speed"] if seg.get("speed") else seg["duration"]
    return total


def pick_rush(board: dict, actuals: list[tuple[str, float, float]], lead: float,
              limit: float) -> dict | None:
    """Adaptive live-wait rush so the final cut fits the limit.

    actuals: (seg id, start, end) on the recorded timeline. Returns None
    when the cut already fits (0.5 s grace: rushing a whole wait to save
    a blink would shrink the video for nothing). Else the smallest speed
    in (2, 4) whose span saves the excess, as {"seg", "span", "speed",
    "tag"}. Raises RuntimeError when even 4x cannot fit the limit.
    """
    if not actuals:
        raise RuntimeError("no recorded segments; cannot plan a rush")
    excess = (actuals[-1][2] - lead) - limit
    if excess <= 0.5:
        return None
    rushed = [seg for seg in board.get("segments", []) if seg.get("rush")]
    if not rushed:
        raise RuntimeError(f"cut overruns by {excess:.1f}s with no rush window to absorb it")
    seg = rushed[0]
    bounds = {sid: (start, end) for sid, start, end in actuals}
    start, end = bounds[seg["id"]]
    first = seg["rush"].get("first", 0)
    last = seg["rush"].get("last", 0)
    span = (start + first, end - last)
    if span[1] - span[0] <= 0.5:
        raise RuntimeError(f"rush window on {seg['id']} is empty; cannot fit {limit:g}s")
    for speed in (2, 4):
        if (span[1] - span[0]) * (1 - 1 / speed) >= excess - 0.05:
            return {"seg": seg["id"], "span": span, "speed": speed, "tag": f"{speed}×"}
    raise RuntimeError(
        f"live wait overruns by {excess:.1f}s; even 4x cannot fit {limit:g}s"
    )


def final_times(actuals: list[tuple[str, float, float]], lead: float,
                spans: list[tuple[float, float, int]]) -> list[tuple[str, float, float]]:
    """Per-segment times on the final cut (lead trimmed, spans rushed)."""

    def at(moment: float) -> float:
        saved = 0.0
        for start, end, speed in spans:
            low, high = max(start, lead), min(end, moment)
            if high > low:
                saved += (high - low) * (1 - 1 / speed)
        return moment - lead - saved

    return [(sid, at(start), at(end)) for sid, start, end in actuals]


def apply_rush(board: dict, actuals: list[tuple[str, float, float]], lead: float,
               limit: float, webm: Path, sped_path: Path):
    """Pick and apply the live-wait rush. Returns (video_src, spans, final_len).

    No rush when the cut already fits. Raises RuntimeError when even 4x
    cannot fit the limit, and CalledProcessError when ffmpeg fails.
    """
    rush = pick_rush(board, actuals, lead, limit)
    if rush is None:
        return webm, [], actuals[-1][2]
    start, end = rush["span"]
    final_len = speed_spans(webm, [(start, end)], actuals[-1][2], sped_path,
                            rush["tag"], rush["speed"])
    saved = (end - start) * (1 - 1 / rush["speed"])
    print(f"rushed {rush['seg']} wait at {rush['tag']} (saved {saved:.1f}s)")
    return sped_path, [(start, end, rush["speed"])], final_len


def append_final_cut(timeline_path: Path, board: dict,
                     actuals: list[tuple[str, float, float]], lead: float,
                     spans: list[tuple[float, float, int]]) -> None:
    """Append per-segment times on the final cut to the timeline file."""
    titles = {seg["id"]: " ".join(seg["caption"].split()) for seg in board["segments"]}
    lines = ["# final cut (lead trimmed, live wait rushed)"]
    for sid, start, end in final_times(actuals, lead, spans):
        lines.append(f"{fmt_time(start)} --> {fmt_time(end)} {sid} {titles.get(sid, '')}")
    with open(timeline_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def print_plan(board: dict, limit_s: int) -> float:
    total = 0.0
    for seg in board["segments"]:
        print(f"{seg['id']} {fmt_time(total)} +{seg['duration']}s {seg['page']} {seg.get('title', '')}")
        total += seg["duration"]
    print(f"total {total:g}s / {limit_s}s")
    return total
