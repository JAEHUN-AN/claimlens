#!/usr/bin/env python3
"""Record the 45 s vertical cut from docs/video/vertical.json.

Mobile emulation (360x640 CSS, sharp 720x1280 output), big captions,
same overlay/cursor/camera helpers as the main video. Output under
out/video/: claimlens_vertical.mp4 (H.264 + AAC) plus the silent webm,
timeline_vertical.txt and midpoint PNGs.

Usage:
    uv run python scripts/record_vertical.py [--music track.mp3]
    uv run python scripts/record_vertical.py --dry-run
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import video_lib as V

ROOT = Path(__file__).resolve().parent.parent
CARDS = ROOT / "docs" / "video" / "cards" / "cards.html"


def dry_run(board: dict) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        texts = V.page_texts_for(ROOT, Path(tmp), {"cards": CARDS})
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
    total = V.print_plan(board, 45)
    if round(total) != 45:
        errors.append(f"want exactly 45 s, got {total:g} s")
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
    code = dry_run(board)
    if code:
        return code
    out_dir.mkdir(parents=True, exist_ok=True)
    V.clean_out(out_dir, ("claimlens_vertical.*", "timeline_vertical.txt", "vv-*_mid.png"))
    overlays = [V.overlay_js(root, font_px=34), V.overlay_fx_js(root)]
    server, base = V.serve(root)
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
            except PlaywrightError as exc:
                if "ffmpeg" in str(exc).lower():
                    print("playwright's ffmpeg is missing; run: uv run playwright install ffmpeg", file=sys.stderr)
                    return 2
                raise
            try:
                for overlay in overlays:
                    page.add_init_script(script=overlay)
                urls = {"demo": f"{base}/docs/demo.html"}
                for cid in V.CARD_IDS:
                    urls[f"card:{cid}"] = f"{base}/docs/video/cards/cards.html#{cid}"
                total = V.run_segments(
                    page, board, urls, out_dir, overlays, png_prefix="vv-",
                    timeline="timeline_vertical.txt", dot0=(180.0, 320.0),
                )
                video = page.video
                context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
    if video is None:
        print("no video was recorded", file=sys.stderr)
        return 2
    webm = out_dir / "claimlens_vertical.webm"
    Path(str(video.path())).rename(webm)
    print(f"wrote {webm}")
    if not V.have_ffmpeg():
        print("ffmpeg not found; .webm kept, .mp4 skipped", file=sys.stderr)
        return 2
    mp4 = out_dir / "claimlens_vertical.mp4"
    try:
        V.mux_sound(webm, mp4, total, music=Path(music) if music else None)
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed:\n{(exc.stderr or '')[-800:]}", file=sys.stderr)
        return 2
    print(f"wrote {mp4}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="record the vertical cut")
    parser.add_argument("--storyboard", default="docs/video/vertical.json")
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
