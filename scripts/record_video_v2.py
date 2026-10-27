#!/usr/bin/env python3
"""Record the 180 s demo video v2 from docs/video/storyboard-v2.json.

v1 plus direction: cold-open and chapter cards, camera zoom + spotlight,
micro-motion, a phone-frame segment, a Meta tools card, and ffmpeg sound
(voice bed + optional music). Output under out/video/: the silent webm,
claimlens_demo_v2.mp4 (H.264 + AAC), timeline_v2.txt and midpoint PNGs.

Usage:
    uv run python scripts/record_video_v2.py [--music track.mp3]
    uv run python scripts/record_video_v2.py --dry-run
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
VOICE_WAV = ROOT / "samples" / "audio" / "W_factory_fall_en.wav"
VOICE_LEN_S = 6.0


def extra_texts() -> dict[str, Path]:
    return {
        "cards": ROOT / "docs" / "video" / "cards" / "cards.html",
        "phone": ROOT / "docs" / "video" / "phone.html",
    }


def dry_run(board: dict) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        texts = V.page_texts_for(ROOT, Path(tmp), extra_texts())
        for cid in V.CARD_IDS:
            texts[f"card:{cid}"] = texts["cards"]
        errors = V.validate(ROOT, board, texts, 190)
        errors += V.check_assets(ROOT, board, texts)
    for name, path in extra_texts().items():
        if not path.exists():
            errors.append(f"missing {name} page: {path}")
    for hook in V.BASE_HOOKS:
        if hook not in V.overlay_js(ROOT):
            errors.append(f"overlay missing {hook}")
    for hook in V.FX_HOOKS:
        if hook not in V.overlay_fx_js(ROOT):
            errors.append(f"overlay_fx missing {hook}")
    if not VOICE_WAV.exists():
        errors.append(f"voice bed missing: {VOICE_WAV}")
    total = V.print_plan(board, 180)
    if round(total) != 180:
        errors.append(f"want exactly 180 s, got {total:g} s")
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
    if not VOICE_WAV.exists():
        print(f"voice bed not found: {VOICE_WAV}", file=sys.stderr)
        return 2
    board = json.loads(board_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        shots = V.build_shots(root, Path(tmp))
        code = dry_run(board)
        if code:
            return code
        out_dir.mkdir(parents=True, exist_ok=True)
        V.clean_out(out_dir, ("claimlens_demo_v2.*", "timeline_v2.txt", "v2-*_mid.png"))
        overlays = [V.overlay_js(root), V.overlay_fx_js(root)]
        server, base = V.serve(root)
        try:
            with sync_playwright() as pw:
                try:
                    browser = pw.chromium.launch(headless=True)
                    context = browser.new_context(
                        viewport={"width": 1280, "height": 720}, record_video_dir=str(out_dir)
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
                    urls.update({k: f"{base}/out/video/shots/{v.name}" for k, v in shots.items()})
                    urls["phone"] = f"{base}/docs/video/phone.html"
                    for cid in V.CARD_IDS:
                        urls[f"card:{cid}"] = f"{base}/docs/video/cards/cards.html#{cid}"
                    for shot in shots.values():
                        dest = out_dir / "shots" / shot.name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(shot.read_bytes())
                    total = V.run_segments(page, board, urls, out_dir, overlays, png_prefix="v2-", timeline="timeline_v2.txt")
                    video = page.video
                    context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
    if video is None:
        print("no video was recorded", file=sys.stderr)
        return 2
    webm = out_dir / "claimlens_demo_v2.webm"
    Path(str(video.path())).rename(webm)
    print(f"wrote {webm}")
    if not V.have_ffmpeg():
        print("ffmpeg not found; .webm kept, .mp4 skipped", file=sys.stderr)
        return 2
    start = V.voice_at(board)
    voice = (VOICE_WAV, start if start is not None else 0.0, VOICE_LEN_S)
    mp4 = out_dir / "claimlens_demo_v2.mp4"
    try:
        V.mux_sound(webm, mp4, total, voice=voice, music=Path(music) if music else None)
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed:\n{(exc.stderr or '')[-800:]}", file=sys.stderr)
        return 2
    print(f"wrote {mp4}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="record the demo video v2")
    parser.add_argument("--storyboard", default="docs/video/storyboard-v2.json")
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
