#!/usr/bin/env python3
"""Record the 45 s vertical cut v3 from docs/video/vertical-v3.json.

Hook, a real live drop on the phone (recorded in real time, played
back 2x with a "2x" tag), tap 22,500, mismatch quotes, link card.
Mobile emulation (360x640 CSS, sharp 720x1280 output). Output under
out/video/: claimlens_vertical_v3.mp4 (H.264 + AAC) plus the silent
webm, timeline_vertical_v3.txt and midpoint PNGs.

Usage:
    uv run python scripts/record_vertical_v3.py [--music track.mp3]
    uv run python scripts/record_vertical_v3.py --dry-run
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import video_lib as V

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "docs" / "video" / "cards" / "cards.html"


def dry_run(board: dict) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        texts = V.page_texts_for(ROOT, Path(tmp), {"cards": CARDS})
        texts["live"] = texts["demo"]
        for cid in V.CARD_IDS:
            texts[f"card:{cid}"] = texts["cards"]
        errors = V.validate(ROOT, board, texts, 44)
        errors += V.check_assets(ROOT, board, texts)
    if not CARDS.exists():
        errors.append(f"missing cards page: {CARDS}")
    for hook in V.BASE_HOOKS:
        if hook not in V.overlay_js(ROOT, font_px=34):
            errors.append(f"overlay missing {hook}")
    for hook in V.FX_HOOKS:
        if hook not in V.overlay_fx_js(ROOT):
            errors.append(f"overlay_fx missing {hook}")
    V.print_plan(board, 45)
    # Storyboard `speed` is the planning budget; at record time the rush
    # window adapts (1x when the wait fits, else the smallest of 2x/4x).
    effective = V.effective_total(board)
    print(f"final cut {effective:g}s / 45s")
    if round(effective) != 45:
        errors.append(f"want exactly 45 s of final cut, got {effective:g} s")
    if not board.get("segments") or board["segments"][-1]["id"] != "vlink":
        errors.append("last segment must be the link card")
    if errors:
        print("DRY RUN: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("DRY RUN: OK")
    return 0


def record(root: Path, board_path: Path, out_dir: Path, music: str | None) -> int:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed; run: uv sync", file=sys.stderr)
        return 2
    if music and not Path(music).exists():
        print(f"music file not found: {music}", file=sys.stderr)
        return 2
    board = json.loads(board_path.read_text(encoding="utf-8"))
    if V.uses_live(board) and not V.live_key_present(root):
        print("live segments need META_API_KEY in the environment or .env", file=sys.stderr)
        return 2
    code = dry_run(board)
    if code:
        return code
    out_dir.mkdir(parents=True, exist_ok=True)
    V.clean_out(out_dir, ("claimlens_vertical_v3.*", "timeline_vertical_v3.txt", "vv3-*_mid.png"))
    overlays = [V.overlay_js(root, font_px=34), V.overlay_fx_js(root)]
    server, base = V.serve(root)
    live_proc, live_base = (None, None)
    if V.uses_live(board):
        try:
            live_proc, live_base = V.start_live_server(root)
        except RuntimeError as exc:
            print(f"live server: {exc}", file=sys.stderr)
            server.shutdown()
            return 2
    actuals: list[tuple[str, float, float]] = []
    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(channel="msedge", headless=True)
                context = browser.new_context(
                    viewport={"width": 360, "height": 640},
                    device_scale_factor=2,
                    is_mobile=True,
                    has_touch=True,
                    record_video_dir=str(out_dir),
                    record_video_size={"width": 720, "height": 1280},
                )
                page = context.new_page()
                video_t0 = time.monotonic()
            except PlaywrightError as exc:
                if "ffmpeg" in str(exc).lower():
                    print("playwright's ffmpeg is missing; run: uv run playwright install ffmpeg", file=sys.stderr)
                    return 2
                raise
            try:
                for overlay in overlays:
                    page.add_init_script(script=overlay)
                urls = {"demo": f"{base}/docs/demo.html"}
                if live_base:
                    urls["live"] = f"{live_base}/docs/demo.html"
                for cid in V.CARD_IDS:
                    urls[f"card:{cid}"] = f"{base}/docs/video/cards/cards.html#{cid}"
                V.run_segments(
                    page, board, urls, out_dir, overlays, png_prefix="vv3-",
                    timeline="timeline_vertical_v3.txt", dot0=(180.0, 320.0),
                    root=root, t0=video_t0, actuals=actuals,
                )
                video = Path(str(page.video.path())) if page.video else None  # path must be read while Playwright runs
                context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        if live_proc is not None:
            live_proc.terminate()
    if video is None:
        print("no video was recorded", file=sys.stderr)
        return 2
    webm = out_dir / "claimlens_vertical_v3.webm"
    video.rename(webm)
    print(f"wrote {webm}")
    if not V.have_ffmpeg():
        print("ffmpeg not found; .webm kept, .mp4 skipped", file=sys.stderr)
        return 2
    mp4 = out_dir / "claimlens_vertical_v3.mp4"
    lead = actuals[0][1] if actuals else 0.0
    try:
        video_src, spans, final_len = V.apply_rush(
            board, actuals, lead, 45, webm, out_dir / "claimlens_vertical_v3_sped.mp4"
        )
    except (subprocess.CalledProcessError, RuntimeError, ValueError) as exc:
        print(f"rush failed: {exc}", file=sys.stderr)
        return 2
    V.append_final_cut(out_dir / "timeline_vertical_v3.txt", board, actuals, lead, spans)
    if V.final_times(actuals, lead, spans)[-1][2] > 45.05:
        print("final cut exceeds 45 s; failing instead of cutting the ending", file=sys.stderr)
        return 2
    try:
        V.mux_sound(video_src, mp4, final_len - lead, music=Path(music) if music else None,
                    lead=lead)
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed:\n{(exc.stderr or '')[-800:]}", file=sys.stderr)
        return 2
    print(f"wrote {mp4}")
    try:
        diff = V.check_first_frame(mp4, board, out_dir, "vv3-")
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"frame check failed: {exc}", file=sys.stderr)
        return 2
    print(f"frame check OK (diff {diff:.1f})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="record the vertical cut v3")
    parser.add_argument("--storyboard", default="docs/video/vertical-v3.json")
    parser.add_argument("--out", default="out/video")
    parser.add_argument("--music", default=None, help="optional music bed (rights-cleared file)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    board = json.loads((ROOT / args.storyboard).read_text(encoding="utf-8"))
    if args.dry_run:
        return dry_run(board)
    return record(ROOT, ROOT / args.storyboard, ROOT / args.out, args.music)


if __name__ == "__main__":
    raise SystemExit(main())
