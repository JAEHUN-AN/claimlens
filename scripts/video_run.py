"""Browser-run side of the demo-video recorders: server, pacing, actions."""

import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

__all__ = [
    "Clock",
    "clean_out",
    "drop_payload",
    "fmt_time",
    "goto",
    "live_key_present",
    "locate",
    "run_action",
    "run_segments",
    "serve",
    "start_live_server",
    "uses_live",
]

DROP_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

DROP_JS = """(el, files) => {
  const dt = new DataTransfer();
  for (const f of files) {
    const bin = atob(f.data);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    dt.items.add(new File([bytes], f.name, {type: f.type}));
  }
  el.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
}"""


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
        # Captions fade in (~260 ms); on 1 s chapter cards the midpoint can land mid-fade.
        vis = False
        for _ in range(10):
            vis = self.page.evaluate(
                "()=>{const c=document.getElementById('vcap');"
                "return !!c&&c.textContent.length>0&&getComputedStyle(c).opacity==='1';}"
            )
            if vis:
                break
            time.sleep(0.06)
        if not vis:
            raise RuntimeError(f"{self.seg_id}: no visible caption at midpoint")
        self.page.screenshot(path=str(self.mid_path))
        self.shot = True


def locate(page, act):
    base = page.frame_locator(act["frame"]) if act.get("frame") else page
    loc = base.locator(act["selector"])
    return loc.nth(act["nth"]) if "nth" in act else loc


def drop_payload(root: Path, files: list[str]) -> list[dict[str, str]]:
    """File bytes as base64 for the drop dispatch. Pure; raises if missing."""
    payload = []
    for name in files:
        blob = (root / name).read_bytes()
        suffix = Path(name).suffix.lower()
        if suffix not in DROP_MIME:
            raise ValueError(f"drop needs an image, got {name}")
        payload.append(
            {"name": Path(name).name, "type": DROP_MIME[suffix],
             "data": base64.b64encode(blob).decode("ascii")}
        )
    return payload


def uses_live(board: dict) -> bool:
    """True when any segment shows the live page."""
    for seg in board.get("segments", []):
        if seg.get("page") == "live":
            return True
        for act in seg.get("actions", []):
            if act.get("op") == "goto" and act.get("page") == "live":
                return True
    return False


def live_key_present(root: Path) -> bool:
    """META_API_KEY in the environment or the repo .env (read-only)."""
    if os.environ.get("META_API_KEY"):
        return True
    try:
        from dotenv import dotenv_values
    except ImportError:
        return False
    env_file = root / ".env"
    if not env_file.exists():
        return False
    return bool(dotenv_values(env_file).get("META_API_KEY"))


def _health_is_live(base: str) -> bool:
    """True when /api/health answers mode live; False while starting up."""
    try:
        with urllib.request.urlopen(base + "/api/health", timeout=2) as resp:
            return json.loads(resp.read().decode("utf-8")).get("mode") == "live"
    except (OSError, ValueError):
        return False


def start_live_server(root: Path):
    """Run `claimlens serve` on an ephemeral port; return (proc, base url).

    Fails loudly when the server does not answer /api/health as live.
    The caller must terminate the process.
    """
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", "from claimlens.serve import serve_forever; serve_forever(0)"],
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    try:
        line = proc.stdout.readline() if proc.stdout else ""
    except (OSError, ValueError):
        line = ""
    match = re.search(r"http://127\.0\.0\.1:(\d+)", line)
    if not match:
        proc.terminate()
        try:
            out = line + (proc.communicate(timeout=5)[0] or "")
        except subprocess.TimeoutExpired:
            proc.kill()
            out = line
        raise RuntimeError(f"live server did not start: {out.strip()[-300:]}")
    base = f"http://127.0.0.1:{match.group(1)}"
    for _ in range(150):
        if _health_is_live(base):
            return proc, base
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("live server never answered /api/health as live")


def goto(page, url: str, caption: str, dot, overlays: list[str]) -> None:
    page.goto(url)
    page.wait_for_load_state("load")
    for overlay in overlays:
        page.evaluate(overlay)
    page.evaluate("(t)=>window.__cap(t)", caption)
    page.evaluate("([x,y])=>window.__place(x,y)", list(dot))


def run_action(page, act: dict, clock: Clock, urls: dict[str, str], caption: str, dot,
               overlays, root: Path | None = None):
    op = act["op"]
    if op == "hold":
        clock.sleep(act["seconds"])
        return None, None
    if op == "goto":
        goto(page, urls[act["page"]], caption, dot, overlays)
        return act["page"], None
    if op == "wait_for":
        base = page.frame_locator(act["frame"]) if act.get("frame") else page
        # Locator.wait_for works for both a page and a frame locator (FrameLocator has no wait_for_selector).
        base.locator(act["selector"]).first.wait_for(state="visible", timeout=act.get("timeout", 20000))
        return None, None
    if op == "dropfiles":
        loc = locate(page, act)
        loc.wait_for(state="visible", timeout=10000)
        loc.evaluate("el=>el.scrollIntoView({behavior:'smooth',block:'center',inline:'center'})")
        time.sleep(0.8)
        box = loc.bounding_box()
        point = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.evaluate("([x,y])=>window.__dot(x,y,600)", list(point))
        payload = drop_payload(root or Path.cwd(), act.get("files", []))
        loc.evaluate(DROP_JS, payload)
        page.evaluate("()=>window.__pulse()")
        return None, point
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
            "([x,y,s,m,w,h])=>window.__zoom(x,y,s,m,w,h)",
            [point[0], point[1], act.get("scale", 1.6), act.get("ms", 600),
             box["width"], box["height"]],
        )
    return None, point


def run_segments(page, board: dict, urls, out_dir: Path, overlays, png_prefix="",
                 timeline="timeline.txt", dot0=(640.0, 360.0), root=None, t0=None,
                 actuals=None):
    current: str | None = None
    dot = [dot0[0], dot0[1]]
    rows = []
    elapsed = 0.0
    origin = t0
    for seg in board["segments"]:
        seg_start = time.monotonic()
        if origin is None:
            origin = seg_start
        if seg["page"] != current:
            goto(page, urls[seg["page"]], seg["caption"], dot, overlays)
            current = seg["page"]
        else:
            page.evaluate("(t)=>window.__cap(t)", seg["caption"])
        clock = Clock(page, seg["id"], seg["duration"], out_dir / f"{png_prefix}{seg['id']}_mid.png")
        for act in seg.get("actions", []):
            moved, point = run_action(page, act, clock, urls, seg["caption"], dot, overlays, root)
            if point:
                dot = [point[0], point[1]]
            if moved:
                current = moved
        clock.finish()
        seg_end = time.monotonic()
        if actuals is not None:
            actuals.append((seg["id"], seg_start - origin, seg_end - origin))
        rows.append((seg, seg_start - origin, seg_end - origin, elapsed))
        elapsed += seg["duration"]
    lead = rows[0][1] if rows else 0.0
    lines = []
    for seg, start, end, planned in rows:
        one_line = " ".join(seg["caption"].split())
        lines.append(
            f"{fmt_time(start - lead)} --> {fmt_time(end - lead)} {seg['id']} {one_line} "
            f"(planned {fmt_time(planned)} --> {fmt_time(planned + seg['duration'])})"
        )
    (out_dir / timeline).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return elapsed
