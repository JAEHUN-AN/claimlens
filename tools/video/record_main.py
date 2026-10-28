#!/usr/bin/env python3
"""Record the 180 s demo video from tools/video/storyboard-main.json.

v2 plus the Round 5 product: a thesis card, a real live run (claimlens
serve started inside the script, new photos dropped, real wait on
screen), the Mismatch scene, and the checks-you-cannot-skip walkthrough.
Output under out/video/: the silent webm, claimlens_demo_v3.mp4
(H.264 + AAC), timeline_v3.txt and midpoint PNGs.

Usage:
    uv run python tools/video/record.py main [--music track.mp3]
    uv run python tools/video/record.py main --dry-run
    uv run python tools/video/record.py main --post-only [--music track.mp3]
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import video_lib as V
import video_post as P

ROOT = Path(__file__).resolve().parent.parent.parent
VOICE_WAV = ROOT / "samples" / "audio" / "W_factory_fall_en.wav"
VOICE_LEN_S = 6.0


def extra_texts() -> dict[str, Path]:
    return {
        "cards": ROOT / "tools" / "video" / "cards" / "cards.html",
        "phone": ROOT / "tools" / "video" / "phone.html",
    }


def dry_run(board: dict) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        texts = V.page_texts_for(ROOT, Path(tmp), extra_texts())
        texts["live"] = texts["demo"]
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
    if not board.get("segments") or board["segments"][-1]["id"] != "closing":
        errors.append("last segment must be the closing card")
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
    if V.uses_live(board) and not V.live_key_present(root):
        print("live segments need META_API_KEY in the environment or .env", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        shots = V.build_shots(root, Path(tmp))
        code = dry_run(board)
        if code:
            return code
        out_dir.mkdir(parents=True, exist_ok=True)
        V.clean_out(out_dir, ("claimlens_demo_v3.*", "timeline_v3.txt", "v3-*_mid.png"))
        overlays = [V.overlay_js(root), V.overlay_fx_js(root)]
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
                        viewport={"width": 1280, "height": 720}, record_video_dir=str(out_dir),
                        record_video_size={"width": 1280, "height": 720}
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
                    urls.update({k: f"{base}/out/video/shots/{v.name}" for k, v in shots.items()})
                    urls["phone"] = f"{base}/tools/video/phone.html"
                    for cid in V.CARD_IDS:
                        urls[f"card:{cid}"] = f"{base}/tools/video/cards/cards.html#{cid}"
                    for shot in shots.values():
                        dest = out_dir / "shots" / shot.name
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(shot.read_bytes())
                    total = V.run_segments(page, board, urls, out_dir, overlays, png_prefix="v3-",
                                           timeline="timeline_v3.txt", root=root,
                                           t0=video_t0, actuals=actuals)
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
    webm = out_dir / "claimlens_demo_v3.webm"
    video.rename(webm)
    print(f"wrote {webm}")
    lead = actuals[0][1] if actuals else 0.0
    P.save_actuals(out_dir / "claimlens_demo_v3_actuals.json", actuals, lead, total)
    start = V.voice_at(board)
    voice = (VOICE_WAV, start if start is not None else 0.0, VOICE_LEN_S)
    return P.run_post(board, out_dir, webm, actuals, lead, total,
                      Path(music) if music else None, "v3-", "timeline_v3.txt", 180,
                      voice=voice)


def post_only(root: Path, board_path: Path, out_dir: Path, music: str | None,
              webm_arg: str | None, actuals_arg: str | None, lead_arg: float | None) -> int:
    """Redo rush, mux, and frame check from a saved recording. No browser."""
    if music and not Path(music).exists():
        print(f"music file not found: {music}", file=sys.stderr)
        return 2
    board = json.loads(board_path.read_text(encoding="utf-8"))
    if dry_run(board):
        return 1
    try:
        webm, actuals, lead = P.resolve_post_inputs(
            board, out_dir, "claimlens_demo_v3.webm", "claimlens_demo_v3_actuals.json",
            "timeline_v3.txt", "v3-", webm_arg, actuals_arg, lead_arg,
        )
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"post-only: {exc}", file=sys.stderr)
        return 2
    total = sum(seg["duration"] for seg in board["segments"])
    start = V.voice_at(board)
    voice = (VOICE_WAV, start if start is not None else 0.0, VOICE_LEN_S)
    return P.run_post(board, out_dir, webm, actuals, lead, total,
                      Path(music) if music else None, "v3-", "timeline_v3.txt", 180,
                      voice=voice)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="record the demo video v3")
    parser.add_argument("--storyboard", default="tools/video/storyboard-main.json")
    parser.add_argument("--out", default="out/video")
    parser.add_argument("--music", default=None, help="optional music bed (rights-cleared file)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--post-only", action="store_true",
                        help="redo rush/mux/frame check from the saved webm + actuals (no browser)")
    parser.add_argument("--webm", default=None, help="post-only input (default: the recorded webm)")
    parser.add_argument("--actuals", default=None, help="post-only measurement file")
    parser.add_argument("--lead", type=float, default=None, help="post-only lead override (seconds)")
    args = parser.parse_args(argv)
    board = json.loads((ROOT / args.storyboard).read_text(encoding="utf-8"))
    if args.dry_run:
        return dry_run(board)
    if args.post_only:
        return post_only(ROOT, ROOT / args.storyboard, ROOT / args.out, args.music,
                         args.webm, args.actuals, args.lead)
    return record(ROOT, ROOT / args.storyboard, ROOT / args.out, args.music)


if __name__ == "__main__":
    raise SystemExit(main())
