"""Record the 3-minute submission video, or dry-run the storyboard.

Record (owner run, needs Edge): serves the repo root on 127.0.0.1, walks
docs/video/storyboard.json with Playwright (Edge channel, 1280x720) and
writes out/video/claimlens_demo.webm + timeline.txt + one midpoint PNG per
segment. Never commit out/.

Dry run (--dry-run, no browser): validates durations, captions and ops, and
checks every selector's tokens against docs/demo.html or the generated shot
pages. Safe to run in the sandbox.
"""

import argparse
import html
import json
import re
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SHOTS = ("readme", "agent-eval", "masking", "eval", "tooling")
OPS = ("click", "move", "scroll_to", "wait_for", "hold", "goto")
LIMIT_S = 180

OVERLAY_JS = """(()=>{
const init=()=>{
if(document.getElementById('vcap'))return;
const css=document.createElement('style');
css.textContent=`html.vrec *{cursor:none!important}
#vcap{position:fixed;left:0;right:0;bottom:0;z-index:2147483647;pointer-events:none;
background:rgba(10,10,12,.72);color:#fff;font:500 23px/1.45 system-ui,sans-serif;
padding:.55rem 1.2rem .7rem;opacity:0;transition:opacity .25s ease}
#vdot{position:fixed;left:0;top:0;width:18px;height:18px;margin:-9px 0 0 -9px;
border-radius:50%;background:rgba(0,100,224,.25);border:3px solid #0064e0;
z-index:2147483647;pointer-events:none}
#vdot.pulse{animation:vpulse .6s ease}
@keyframes vpulse{0%{box-shadow:0 0 0 0 rgba(0,100,224,.55)}
100%{box-shadow:0 0 0 22px rgba(0,100,224,0)}}`;
document.head.appendChild(css);
document.documentElement.classList.add('vrec');
const cap=document.createElement('div');cap.id='vcap';document.body.appendChild(cap);
const dot=document.createElement('div');dot.id='vdot';document.body.appendChild(dot);
let dx=innerWidth/2,dy=innerHeight/2,raf=null;
window.__cap=t=>{cap.style.opacity='0';
setTimeout(()=>{cap.textContent=t;cap.style.opacity='1';},260);};
window.__dot=(x,y,ms)=>new Promise(res=>{
if(raf)cancelAnimationFrame(raf);
const x0=dx,y0=dy,t0=performance.now();
const step=n=>{const k=Math.min(1,(n-t0)/ms),e=1-Math.pow(1-k,3);
dx=x0+(x-x0)*e;dy=y0+(y-y0)*e;
dot.style.transform=`translate(${dx}px,${dy}px)`;
if(k<1)raf=requestAnimationFrame(step);else res();};
raf=requestAnimationFrame(step);});
window.__pulse=()=>{dot.classList.remove('pulse');
void dot.offsetWidth;dot.classList.add('pulse');};};
if(document.body)init();
else document.addEventListener('DOMContentLoaded',init,{once:true});})();
"""

SHOT_CSS = (
    "body{font:16px/1.5 system-ui,sans-serif;color:#111;max-width:1120px;"
    "margin:0 auto;padding:1.2rem;background:#fff}"
    "table{border-collapse:collapse;margin:.6rem 0}"
    "th,td{border:1px solid #999;padding:.25rem .5rem;text-align:left;font-size:14px}"
    "h1{font-size:1.3rem}h2{font-size:1.1rem}.src{color:#555;font-size:13px}"
    "img{max-width:100%}.pair{display:grid;grid-template-columns:1fr 1fr;gap:1rem}"
    "figure{margin:.4rem 0}figcaption{font-size:13px;color:#333}#shot-end{height:1px}"
)


def _inline(text: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = html.escape(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def _blocks(lines: list[str]) -> str:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")
            i += 1
            continue
        if line.startswith("# "):
            out.append(f"<h2>{_inline(line[2:])}</h2>")
            i += 1
            continue
        if line.startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            rows = [r for r in rows if not all(re.fullmatch(r":?-{1,}:?", c or "-") for c in r)]
            head, body = rows[0], rows[1:]
            out.append(
                "<table><tr>"
                + "".join(f"<th>{_inline(c)}</th>" for c in head)
                + "</tr>"
                + "".join(
                    "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                    for r in body
                )
                + "</table>"
            )
            continue
        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(c)}</li>" for c in items) + "</ul>")
            continue
        out.append(f"<p>{_inline(line.strip())}</p>")
        i += 1
    return "\n".join(out)


def _page(title: str, note: str, body: str) -> str:
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>'
        f"<title>{title}</title><style>{SHOT_CSS}</style></head><body>"
        f"<h1>{title}</h1><p class=\"src\">{note}</p>"
        f'<main id="shot">{body}</main><p id="shot-end"></p></body></html>'
    )


def build_shots(root: Path, shots_dir: Path) -> dict[str, Path]:
    """Render local shot pages from repo files. Pure file work, no browser."""
    shots_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    readme = (root / "README.md").read_text(encoding="utf-8").split("\n")
    start = next(i for i, line in enumerate(readme) if line.startswith("## Built vs"))
    stop = next(
        (i for i in range(start + 1, len(readme)) if readme[i].startswith("## ")),
        len(readme),
    )
    paths["readme"] = _write(
        shots_dir, "readme", "Built vs pre-existing", "Source: README.md", _blocks(readme[start:stop])
    )
    agent = (root / "docs" / "agent-eval.md").read_text(encoding="utf-8").split("\n")
    paths["agent-eval"] = _write(
        shots_dir, "agent-eval", "Agent scorecard", "Source: docs/agent-eval.md", _blocks(agent)
    )
    paths["eval"] = _write(
        shots_dir, "eval", "Reading accuracy, photo rows", "Hosted vs open, values verbatim. Full table: docs/eval.md",
        _eval_table(root),
    )
    pairs = [
        ("S2 receipt", "/samples/S2_seoul_worker_bronchitis/receipt_photo.jpg", "/docs/masking/S2_receipt_after.png"),
        ("S3 certificate", "/samples/S3_us_tourist_hip_fracture/medical_certificate_photo.jpg", "/docs/masking/S3_cert_after.png"),
    ]
    body = '<div class="pair">' + "".join(
        f'<figure><img src="{before}"/><figcaption>{label} — before (photo)</figcaption></figure>'
        f'<figure><img src="{after}"/><figcaption>{label} — after (masked)</figcaption></figure>'
        for label, before, after in pairs
    )
    paths["masking"] = _write(shots_dir, "masking", "Masking before / after", "Seals and signatures masked on a copy", body + "</div>")
    log = (root / "docs" / "meta-tooling-log.md").read_text(encoding="utf-8").split("\n")
    paths["tooling"] = _write(
        shots_dir, "tooling", "Tooling log", "Source: docs/meta-tooling-log.md", _blocks(log)
    )
    return paths


def _write(shots_dir: Path, name: str, title: str, note: str, body: str) -> Path:
    path = shots_dir / f"shot_{name}.html"
    path.write_text(_page(title, note, body), encoding="utf-8")
    return path


def _eval_table(root: Path) -> str:
    lines = (root / "docs" / "eval.md").read_text(encoding="utf-8").split("\n")
    head = next(line for line in lines if line.startswith("| sample |"))
    cols = [c.strip() for c in head.strip().strip("|").split("|")]
    keep = ["sample", "total", "lines", "checks", "open_total", "open_lines", "open_checks"]
    idx = [cols.index(k) for k in keep]
    rows = []
    for line in lines[lines.index(head) + 1 :]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != len(cols) or set("".join(cells)) <= set("|-: "):
            continue
        if cells[cols.index("variant")] != "photo":
            continue
        rows.append([cells[i] for i in idx])
    table = (
        "<table><tr>"
        + "".join(f"<th>{_inline(c)}</th>" for c in keep)
        + "</tr>"
        + "".join(
            "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows
        )
        + "</table>"
    )
    return table


def _tokens(selector: str) -> list[str]:
    toks: list[str] = []
    toks += re.findall(r"#([\w-]+)", selector)
    toks += re.findall(r"\.([\w-]+)", selector)
    for match in re.finditer(r"\[([\w-]+)(?:=\"([^\"]*)\"|='([^']*)')?\]", selector):
        toks.append(match.group(1))
        toks += [g for g in (match.group(2), match.group(3)) if g]
    for match in re.finditer(r":has-text\((\"([^\"]*)\"|'([^']*)')\)", selector):
        toks += [g for g in (match.group(2), match.group(3)) if g]
    return toks


def _nav_texts(demo_text: str) -> list[str]:
    match = re.search(r'<script id="demo-data"[^>]*>(.*?)</script>', demo_text, re.DOTALL)
    payload = json.loads(match.group(1))
    return ["Guided flow"] + [s["title"] for s in payload["scenes"]]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d}.{ms % 1000:03d}"


def dry_run(root: Path, sb_path: Path) -> int:
    """Validate the storyboard without a browser. Returns an exit code."""
    raw = sb_path.read_text(encoding="utf-8")
    try:
        label = sb_path.relative_to(root)
    except ValueError:
        label = sb_path.name
    errors: list[str] = []
    if "https://" in raw:
        errors.append("storyboard contains https://")
    sb = json.loads(raw)
    segments = sb.get("segments", [])
    total = sum(s.get("duration", 0) for s in segments)
    if total > LIMIT_S:
        errors.append(f"durations sum to {total}s, over the {LIMIT_S}s limit")
    demo_text = (root / "docs" / "demo.html").read_text(encoding="utf-8")
    nav = _nav_texts(demo_text)
    with tempfile.TemporaryDirectory() as tmp:
        shots = build_shots(root, Path(tmp))
        texts = {"demo": demo_text}
        texts.update({k: v.read_text(encoding="utf-8") for k, v in shots.items()})
        for name in shots:
            if "https://" in texts[name]:
                errors.append(f"shot page {name} contains https://")
        print(f"DRY RUN {label}")
        current: str | None = None
        elapsed = 0
        for seg in segments:
            if not seg.get("caption"):
                errors.append(f"{seg.get('id')}: empty caption")
            if seg.get("duration", 0) <= 0:
                errors.append(f"{seg.get('id')}: bad duration")
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
                if act["op"] == "hold":
                    if act.get("seconds", 0) <= 0:
                        errors.append(f"{seg['id']}: bad hold")
                    continue
                sel = act.get("selector", "")
                for tok in _tokens(sel):
                    if tok not in texts[current]:
                        errors.append(f"{seg['id']}: {tok!r} missing on {current}")
                if current == "demo" and "#scenes button" in sel:
                    for nav_text in re.findall(r':has-text\("([^"]*)"\)', sel):
                        hits = [b for b in nav if nav_text.lower() in b.lower()]
                        if len(hits) != 1:
                            errors.append(
                                f"{seg['id']}: {nav_text!r} matches {len(hits)} nav buttons, want 1"
                            )
            print(f"{seg['id']} {_fmt(elapsed)} +{seg['duration']}s {seg['page']} {seg.get('title', '')}")
            elapsed += seg["duration"]
        print(f"total {total}s / {LIMIT_S}s, shots: {len(shots)} built")
    if errors:
        print("DRY RUN: FAIL")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("DRY RUN: OK")
    return 0


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


def _serve(root: Path):
    handler = partial(_Quiet, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


class _Clock:
    def __init__(self, page, duration: float, mid_path: Path) -> None:
        self.page = page
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
                self._shoot()
            elif target > self.mid:
                time.sleep(max(0.0, self.mid - now))
                self._shoot()
        time.sleep(max(0.0, target - time.monotonic()))

    def finish(self) -> None:
        if not self.shot:
            self._shoot()
        time.sleep(max(0.0, self.end - time.monotonic()))

    def _shoot(self) -> None:
        self.page.screenshot(path=str(self.mid_path))
        self.shot = True


def _locate(page, act):
    loc = page.locator(act["selector"])
    return loc.nth(act["nth"]) if "nth" in act else loc


def _center(page, loc) -> tuple[float, float]:
    loc.evaluate("el=>el.scrollIntoView({behavior:'smooth',block:'center',inline:'center'})")
    time.sleep(0.8)
    box = loc.bounding_box()
    return (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def _action(page, act: dict, clock: _Clock, urls: dict[str, str], caption: str) -> str | None:
    op = act["op"]
    if op == "hold":
        clock.sleep(act["seconds"])
        return None
    if op == "goto":
        page.goto(urls[act["page"]])
        page.wait_for_load_state("load")
        page.evaluate("(t)=>window.__cap(t)", caption)
        return act["page"]
    if op == "wait_for":
        page.wait_for_selector(act["selector"], state="visible", timeout=20000)
        return None
    loc = _locate(page, act)
    loc.wait_for(state="visible", timeout=10000)
    if op == "scroll_to":
        loc.evaluate("el=>el.scrollIntoView({behavior:'smooth',block:'center'})")
        clock.sleep(0.9)
        return None
    x, y = _center(page, loc)
    page.evaluate("([x,y])=>window.__dot(x,y,600)", [x, y])
    if op == "click":
        page.evaluate("()=>window.__pulse()")
        loc.click(timeout=10000)
    return None


def record(root: Path, sb_path: Path, out_dir: Path) -> int:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    sb = _load(sb_path)
    total = sum(s["duration"] for s in sb["segments"])
    if total > LIMIT_S:
        print(f"storyboard runs {total}s, over the {LIMIT_S}s limit")
        return 1
    try:
        rel = out_dir.resolve().relative_to(root.resolve())
    except ValueError:
        print("out dir must live inside the repo (it is served over http)")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    build_shots(root, out_dir / "shots")
    base_urls = {"demo": "docs/demo.html"}
    base_urls.update({name: f"{rel.as_posix()}/shots/shot_{name}.html" for name in SHOTS})
    server, base = _serve(root)
    urls = {k: f"{base}/{v}" for k, v in base_urls.items()}
    lines = []
    elapsed = 0
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                record_video_dir=str(out_dir),
                record_video_size={"width": 1280, "height": 720},
            )
            page = context.new_page()
            page.add_init_script(OVERLAY_JS)
            current: str | None = None
            for seg in sb["segments"]:
                if seg["page"] != current:
                    page.goto(urls[seg["page"]])
                    page.wait_for_load_state("load")
                    current = seg["page"]
                page.evaluate("(t)=>window.__cap(t)", seg["caption"])
                clock = _Clock(page, seg["duration"], out_dir / f"{seg['id']}_mid.png")
                for act in seg["actions"]:
                    moved = _action(page, act, clock, urls, seg["caption"])
                    if moved:
                        current = moved
                clock.finish()
                one_line = " ".join(seg["caption"].split())
                lines.append(f"{_fmt(elapsed)} --> {_fmt(elapsed + seg['duration'])} {seg['id']} {one_line}")
                elapsed += seg["duration"]
            page.close()
            context.close()
            video_src = Path(page.video.path())
            browser.close()
    except PlaywrightError as exc:
        if "ffmpeg" not in str(exc).lower():
            raise
        print("Video recording needs Playwright's ffmpeg binary (one-time download).")
        print("Run this once, then re-run the recording:")
        print("  uv run playwright install ffmpeg")
        return 1
    finally:
        server.shutdown()
        server.server_close()
    target = out_dir / "claimlens_demo.webm"
    video_src.replace(target)
    (out_dir / "timeline.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"recorded {target} ({elapsed}s, {len(lines)} segments)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Record or dry-run the demo video.")
    parser.add_argument("--dry-run", action="store_true", help="Validate without a browser.")
    parser.add_argument("--storyboard", default="docs/video/storyboard.json")
    parser.add_argument("--out", default="out/video")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    if args.dry_run:
        return dry_run(root, root / args.storyboard)
    return record(root, root / args.storyboard, root / args.out)


if __name__ == "__main__":
    raise SystemExit(main())
