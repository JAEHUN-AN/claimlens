#!/usr/bin/env python3
"""Record the 180 s demo video (v1) from docs/video/storyboard.json.

Headless Chromium visits docs/demo.html and generated doc shot pages,
with a caption bar + cursor dot overlaid by JS. Output: page@*.webm,
twelve segNN_mid.png screenshots and timeline.txt under out/video/.

Usage:
    uv run python scripts/record_video.py            # real recording
    uv run python scripts/record_video.py --dry-run  # validate only
"""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import video_lib as V

ROOT = Path(__file__).resolve().parent.parent

BASE_HOOKS = V.BASE_HOOKS


def dry_run(board: dict, check_overlay: bool = True) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        texts = V.page_texts_for(ROOT, Path(tmp), {})
        errors = V.validate(ROOT, board, texts, 190)
    if check_overlay:
        overlay = V.overlay_js(ROOT)
        for hook in BASE_HOOKS:
            if hook not in overlay:
                errors.append(f"overlay missing {hook}")
    total = V.print_plan(board, 180)
    if round(total) != 180 or len(board["segments"]) != 12:
        errors.append(f"want exactly 12 segments totalling 180 s, got {total:g} s")
    if errors:
        print("DRY RUN: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("DRY RUN: OK")
    return 0


def record(root: Path, board_path: Path, out_dir: Path) -> int:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed; run: uv sync", file=sys.stderr)
        return 2
    board = V.json.loads(board_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        shots = V.build_shots(root, Path(tmp))
        code = dry_run(board, check_overlay=False)
        if code:
            return code
        out_dir.mkdir(parents=True, exist_ok=True)
        V.clean_out(out_dir, ("page@*.webm", "timeline.txt", "seg*_mid.png"))
        overlay = V.overlay_js(root)
        server, base = V.serve(root)
        try:
            with sync_playwright() as pw:
                try:
                    browser = pw.chromium.launch(channel="msedge", headless=True)
                    context = browser.new_context(
                        viewport={"width": 1280, "height": 720}, record_video_dir=str(out_dir),
                        record_video_size={"width": 1280, "height": 720}
                    )
                    page = context.new_page()
                except PlaywrightError as exc:
                    if "ffmpeg" in str(exc).lower():
                        print("playwright's ffmpeg is missing; run: uv run playwright install ffmpeg", file=sys.stderr)
                        return 2
                    raise
                try:
                    page.add_init_script(script=overlay)
                    urls = {"demo": f"{base}/docs/demo.html"}
                    urls.update({k: f"{base}/out/video/shots/{v.name}" for k, v in shots.items()})
                    for shot in shots.values():
                        dest = out_dir / "shots" / shot.name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(shot.read_bytes())
                    V.run_segments(page, board, urls, out_dir, [overlay])
                    final = page.video.path() if page.video else None
                    context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
    print(f"wrote {out_dir}")
    if final:
        print(f"video: {final}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="record the demo video")
    parser.add_argument("--storyboard", default="docs/video/storyboard.json")
    parser.add_argument("--out", default="out/video")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    board = V.json.loads((ROOT / args.storyboard).read_text(encoding="utf-8"))
    if args.dry_run:
        return dry_run(board)
    return record(ROOT, ROOT / args.storyboard, ROOT / args.out)


if __name__ == "__main__":
    raise SystemExit(main())
