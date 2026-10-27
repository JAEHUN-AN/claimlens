"""Browser-run side of the demo-video recorders: server, pacing, actions."""

import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

__all__ = [
    "Clock",
    "clean_out",
    "fmt_time",
    "goto",
    "locate",
    "run_action",
    "run_segments",
    "serve",
]


def fmt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d}.{ms % 1000:03d}"


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


def serve(root: Path):
    handler = partial(_Quiet, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def clean_out(out_dir: Path, patterns: tuple[str, ...]) -> None:
    """Remove this product's stale outputs only; never another cut's files."""
    if not out_dir.exists():
        return
    for pattern in patterns:
        for stale in out_dir.glob(pattern):
            if stale.is_file():
                stale.unlink()
    shots = out_dir / "shots"
    if shots.exists():
        for stale in shots.glob("shot_*.html"):
            if stale.is_file():
                stale.unlink()


class Clock:
    """Segment pacing: holds, a true-midpoint screenshot, and padding."""

    def __init__(self, page, seg_id: str, duration: float, mid_path: Path) -> None:
        self.page = page
        self.seg_id = seg_id
        self.start = time.monotonic()
        self.mid = self.start + duration / 2
        self.end = self.start + duration
        self.mid_path = mid_path
        self.shot = False

    def sleep(self, seconds: float) -> None:
        target = time.monotonic() + seconds
        if not self.shot:
            now = time.monotonic()
            if now >= self.mid:
                self.shoot()
            elif target > self.mid:
                time.sleep(max(0.0, self.mid - now))
                self.shoot()
        time.sleep(max(0.0, target - time.monotonic()))

    def finish(self) -> None:
        if not self.shot:
            time.sleep(max(0.0, self.mid - time.monotonic()))
            self.shoot()
        time.sleep(max(0.0, self.end - time.monotonic()))

    def shoot(self) -> None:
        vis = self.page.evaluate(
            "()=>{const c=document.getElementById('vcap');"
            "return !!c&&c.textContent.length>0&&getComputedStyle(c).opacity==='1';}"
        )
        if not vis:
            raise RuntimeError(f"{self.seg_id}: no visible caption at midpoint")
        self.page.screenshot(path=str(self.mid_path))
        self.shot = True


def locate(page, act):
    base = page.frame_locator(act["frame"]) if act.get("frame") else page
    loc = base.locator(act["selector"])
    return loc.nth(act["nth"]) if "nth" in act else loc


def goto(page, url: str, caption: str, dot, overlays: list[str]) -> None:
    page.goto(url)
    page.wait_for_load_state("load")
    for overlay in overlays:
        page.evaluate(overlay)
    page.evaluate("(t)=>window.__cap(t)", caption)
    page.evaluate("([x,y])=>window.__place(x,y)", list(dot))


def run_action(page, act: dict, clock: Clock, urls: dict[str, str], caption: str, dot, overlays):
    op = act["op"]
    if op == "hold":
        clock.sleep(act["seconds"])
        return None, None
    if op == "goto":
        goto(page, urls[act["page"]], caption, dot, overlays)
        return act["page"], None
    if op == "wait_for":
        base = page.frame_locator(act["frame"]) if act.get("frame") else page
        base.wait_for_selector(act["selector"], state="visible", timeout=20000)
        return None, None
    if op == "unzoom":
        page.evaluate("()=>window.__unzoom()")
        clock.sleep(0.7)
        return None, None
    loc = locate(page, act)
    loc.wait_for(state="visible", timeout=10000)
    if op == "scroll_to":
        loc.evaluate("el=>el.scrollIntoView({behavior:'smooth',block:'center'})")
        clock.sleep(0.9)
        return None, None
    loc.evaluate("el=>el.scrollIntoView({behavior:'smooth',block:'center',inline:'center'})")
    time.sleep(0.8)
    box = loc.bounding_box()
    point = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.evaluate("([x,y])=>window.__dot(x,y,600)", list(point))
    if op == "click":
        page.evaluate("()=>window.__pulse()")
        loc.click(timeout=10000)
    elif op == "zoom":
        page.evaluate(
            "([x,y,s,m])=>window.__zoom(x,y,s,m)",
            [point[0], point[1], act.get("scale", 1.6), act.get("ms", 600)],
        )
    return None, point


def run_segments(page, board: dict, urls, out_dir: Path, overlays, png_prefix="",
                 timeline="timeline.txt", dot0=(640.0, 360.0)):
    current: str | None = None
    dot = [dot0[0], dot0[1]]
    lines = []
    elapsed = 0.0
    for seg in board["segments"]:
        if seg["page"] != current:
            goto(page, urls[seg["page"]], seg["caption"], dot, overlays)
            current = seg["page"]
        else:
            page.evaluate("(t)=>window.__cap(t)", seg["caption"])
        clock = Clock(page, seg["id"], seg["duration"], out_dir / f"{png_prefix}{seg['id']}_mid.png")
        for act in seg.get("actions", []):
            moved, point = run_action(page, act, clock, urls, seg["caption"], dot, overlays)
            if point:
                dot = [point[0], point[1]]
            if moved:
                current = moved
        clock.finish()
        one_line = " ".join(seg["caption"].split())
        lines.append(f"{fmt_time(elapsed)} --> {fmt_time(elapsed + seg['duration'])} {seg['id']} {one_line}")
        elapsed += seg["duration"]
    (out_dir / timeline).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return elapsed
