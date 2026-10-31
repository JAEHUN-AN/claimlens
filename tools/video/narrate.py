"""Scene narration for the v3 cuts (63): edge-tts per scene, mixed under the cut.

Inputs: storyboard narrations, the recorded final-cut timeline, and the
finished mp4. Each narrated segment is synthesized with edge-tts (via
uvx, never a project dependency), placed at its final-cut start with a
small gap after a long predecessor, and re-synthesized faster when it
overruns its scene limit. Voice-bed scenes speak after the recorded
sample ends. The mix keeps the original sound (or a silence bed when
the cut has none) and writes *_narrated.mp4 plus *_narration.srt for
YouTube closed captions.

Live runs need network (edge-tts) and ffmpeg; Claude runs them.
Tests inject a fake synthesizer and pin scheduling, SRT, and command
assembly. Usage:

    uv run python tools/video/narrate.py --storyboard tools/video/storyboard-main.json \\
        --timeline out/video/timeline_v3.txt --mp4 out/video/claimlens_demo_v3.mp4
"""

import argparse
import re
import shutil
import subprocess
import time
import sys
import wave
from pathlib import Path

__all__ = [
    "GAP_S",
    "LIMIT_MARGIN_S",
    "build_items",
    "main",
    "mix_cmd",
    "parse_final_cut",
    "rate_ok",
    "schedule",
    "src_has_audio",
    "synth_cmd",
    "synthesize_scene",
    "wav_duration",
    "write_srt",
]

ROOT = Path(__file__).resolve().parent.parent.parent
GAP_S = 0.25
LIMIT_MARGIN_S = 0.3
TIME_RE = re.compile(r"(\d+):(\d+):([\d.]+)")
RATE_RE = re.compile(r"[+-]\d+%")


def _parse_time(text: str) -> float:
    match = TIME_RE.fullmatch(text.strip())
    if not match:
        raise ValueError(f"bad timestamp {text!r}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_final_cut(timeline: Path) -> dict[str, tuple[float, float]]:
    """Final-cut segment times from a timeline file. Returns id -> (start, end)."""
    lines = timeline.read_text(encoding="utf-8").splitlines()
    marks = [i for i, line in enumerate(lines) if line.startswith("# final cut")]
    if not marks:
        raise ValueError(f"no final-cut section in {timeline}")
    final: dict[str, tuple[float, float]] = {}
    for line in lines[marks[-1] + 1:]:
        if not line.strip():
            continue
        head, sep, rest = line.partition(" --> ")
        tokens = rest.split()
        if not sep or len(tokens) < 2:
            raise ValueError(f"bad timeline line: {line}")
        final[tokens[1]] = (_parse_time(head), _parse_time(tokens[0]))
    if not final:
        raise ValueError(f"no final-cut segments in {timeline}")
    return final


def wav_duration(path: Path) -> float:
    """Duration of a wav file in seconds."""
    with wave.open(str(path)) as wav:
        return wav.getnframes() / wav.getframerate()


def build_items(board: dict, final: dict[str, tuple[float, float]],
                bed_s: float) -> list[dict]:
    """Narrated segments with nominal starts and limits (final-cut times).

    Voice-bed scenes speak after the recorded sample ends. Segments
    without a narration (chapter cards) are skipped; a line may run on
    over the silent cards right after its scene.
    """
    items = []
    segments = board.get("segments", [])
    for pos, seg in enumerate(segments):
        text = seg.get("narration") or ""
        if not text.strip():
            continue
        if seg["id"] not in final:
            raise ValueError(f"segment {seg['id']} missing from the final cut")
        start, end = final[seg["id"]]
        for nxt in segments[pos + 1:]:
            if (nxt.get("narration") or "").strip() or nxt["id"] not in final:
                break
            end = final[nxt["id"]][1]
        if seg.get("sound") == "voice":
            start += bed_s
        items.append({"id": seg["id"], "text": text,
                      "start": start, "limit": end + LIMIT_MARGIN_S})
    return items


def schedule(items: list[dict], durations: dict[str, float],
             gap: float = GAP_S) -> tuple[list[dict], list[str]]:
    """Chain narrations at scene starts. Returns (schedule, over-limit ids)."""
    sched = []
    bad = []
    prev_end = 0.0
    for item in items:
        dur = durations[item["id"]]
        start = max(item["start"], prev_end + gap if sched else item["start"])
        end = start + dur
        ok = end <= item["limit"]
        if not ok:
            bad.append(item["id"])
        sched.append({"id": item["id"], "text": item["text"],
                      "at": round(start, 3), "dur": round(dur, 3),
                      "end": round(end, 3), "limit": item["limit"], "ok": ok})
        prev_end = end
    return sched, bad


def _srt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    return (f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:"
            f"{(ms // 1000) % 60:02d},{ms % 1000:03d}")


def write_srt(sched: list[dict], path: Path) -> None:
    """Full-narration subtitles from the schedule, for YouTube CC."""
    cues = []
    for num, row in enumerate(sched, start=1):
        cues.append(f"{num}\n{_srt_time(row['at'])} --> {_srt_time(row['end'])}"
                    f"\n{row['text']}\n")
    path.write_text("\n".join(cues), encoding="utf-8")


def rate_ok(rate: str) -> bool:
    """edge-tts rate flag shape (+25%, -10%)."""
    return RATE_RE.fullmatch(rate) is not None


def synth_cmd(text: str, out_mp3: Path, voice: str,
              rate: str | None = None) -> list[str]:
    """edge-tts via uvx (never a project dependency)."""
    cmd = ["uvx", "--from", "edge-tts@latest", "edge-tts",
           "--voice", voice, "--text", text, "--write-media", str(out_mp3)]
    if rate is not None:
        cmd += ["--rate", rate]
    return cmd


_SPOKEN = (
    (re.compile(r"\u20a9\s?([\d.,]+)\s*billion"), r"\1 billion won"),
    (re.compile(r"\(est\.\)"), "(estimated)"),
    (re.compile(r"\s*\u2192\s*"), " to "),
    (re.compile(r"\s*\u00b7\s*"), ", "),
    (re.compile(r"\s*\u2014\s*"), ", "),
    (re.compile(r"(\d)\+"), r"\1 plus"),
    (re.compile(r"\s\+\s"), " plus "),
    (re.compile(r"\b(\d+)/(\d+)\b"), r"\1 of \2"),
    (re.compile(r"_"), " "),
    (re.compile(r"\(\d{4}-\d{2}-\d{2},\s*"), "("),
    (re.compile(r"\s*\(?\d{4}-\d{2}-\d{2}\)?,?"), ""),
    (re.compile(r"Try it:.*$"), "Try it at the links on screen."),
)


def spoken(text: str) -> str:
    """What the voice says: symbols, dates and links turned into speech.

    The SRT keeps the written narration; only the synthesized audio uses this.
    """
    for pattern, repl in _SPOKEN:
        text = pattern.sub(repl, text)
    return re.sub(r"\s{2,}", " ", text).strip()


def synthesize_scene(text: str, wav_path: Path, voice: str,
                     rate: str | None = None) -> None:
    """Synthesize one narration to a uniform wav (44.1 kHz mono)."""
    from video_sound import ffmpeg_bin

    mp3 = wav_path.with_suffix(".mp3")
    # The read-aloud service sometimes answers with no audio; retry a little.
    for attempt in range(3):
        done = subprocess.run(synth_cmd(spoken(text), mp3, voice, rate),
                              capture_output=True, text=True)
        if done.returncode == 0 and mp3.exists() and mp3.stat().st_size > 0:
            break
        time.sleep(2 * (attempt + 1))
    else:
        raise subprocess.CalledProcessError(done.returncode, done.args,
                                            done.stdout, done.stderr)
    subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(mp3),
                    "-ar", "44100", "-ac", "1", str(wav_path)],
                   check=True, capture_output=True, text=True)
    mp3.unlink(missing_ok=True)


def src_has_audio(mp4: Path) -> bool:
    """True when the cut carries an audio stream (ffmpeg -i sniff)."""
    from video_sound import ffmpeg_bin

    proc = subprocess.run([ffmpeg_bin(), "-i", str(mp4)], check=False,
                          capture_output=True, text=True)
    return "Audio:" in (proc.stderr or "")


def mix_cmd(src_mp4: Path, clips: list[tuple[Path, float]], total: float,
            dst: Path, silent: bool) -> list[str]:
    """Mix narration clips over the original sound (or a silence bed).

    clips: (wav path, start seconds). Speech at +4 dB under a limiter;
    video stream copied, no re-encode.
    """
    from video_sound import ffmpeg_bin

    if not clips:
        raise ValueError("no narration clips to mix")
    cmd = [ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(src_mp4)]
    if silent:
        cmd += ["-f", "lavfi", "-t", f"{total:.3f}", "-i",
                "anullsrc=r=44100:cl=stereo"]
    for wav, _ in clips:
        cmd += ["-i", str(wav)]
    off = 2 if silent else 1
    parts = []
    for num, (_, at) in enumerate(clips, start=off):
        ms = round(at * 1000)
        parts.append(f"[{num}:a]aresample=44100,aformat=channel_layouts=stereo,"
                     f"adelay={ms}|{ms},volume=1.6[n{num}]")
    labels = "".join(f"[n{num}]" for num in range(off, off + len(clips)))
    parts.append(f"{labels}amix=inputs={len(clips)}:normalize=0[narr]")
    parts.append(f"[{'1' if silent else '0'}:a]aresample=44100,"
                 "aformat=channel_layouts=stereo[orig]")
    parts.append("[orig][narr]amix=inputs=2:normalize=0:duration=longest,"
                 "alimiter=limit=0.95[a]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(dst)]
    return cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="narrate a recorded cut with edge-tts")
    parser.add_argument("--storyboard", required=True)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--mp4", required=True)
    parser.add_argument("--out-dir", default=None,
                        help="wav/srt output dir (default: <mp4 dir>/narration)")
    parser.add_argument("--voice", default="en-US-AndrewNeural")
    parser.add_argument("--rate", default="+25%",
                        help="retry rate for over-limit scenes only")
    parser.add_argument("--voice-bed", default="samples/audio/W_factory_fall_en.wav",
                        help="measured for voice-scene narration starts")
    args = parser.parse_args(argv)
    import json

    from video_sound import VOICE_LEN_S, have_ffmpeg

    if not rate_ok(args.rate):
        print(f"bad --rate {args.rate!r}, want +25% or -10%", file=sys.stderr)
        return 2
    if shutil.which("uvx") is None:
        print("uvx not found; narration needs edge-tts via uvx", file=sys.stderr)
        return 2
    if not have_ffmpeg():
        print("ffmpeg not found", file=sys.stderr)
        return 2
    storyboard = Path(args.storyboard)
    board = json.loads(storyboard.read_text(encoding="utf-8"))
    mp4 = Path(args.mp4)
    out_dir = Path(args.out_dir) if args.out_dir else mp4.parent / "narration"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        final = parse_final_cut(Path(args.timeline))
    except (OSError, ValueError) as exc:
        print(f"timeline: {exc}", file=sys.stderr)
        return 2
    bed_s = 0.0
    if any(seg.get("sound") == "voice" and (seg.get("narration") or "").strip()
           for seg in board.get("segments", [])):
        bed = ROOT / args.voice_bed if not Path(args.voice_bed).is_absolute() else Path(args.voice_bed)
        if not bed.is_file():
            print(f"voice bed not found: {bed}", file=sys.stderr)
            return 2
        # The cut plays only the first VOICE_LEN_S of the sample (mux_sound trims it).
        bed_s = min(wav_duration(bed), VOICE_LEN_S)
    try:
        items = build_items(board, final, bed_s)
    except ValueError as exc:
        print(f"storyboard: {exc}", file=sys.stderr)
        return 2
    if not items:
        print("no narrations in the storyboard", file=sys.stderr)
        return 2
    wavs = {item["id"]: out_dir / f"{item['id']}.wav" for item in items}
    try:
        for item in items:
            synthesize_scene(item["text"], wavs[item["id"]], args.voice)
        durations = {sid: wav_duration(wav) for sid, wav in wavs.items()}
        sched, bad = schedule(items, durations)
        if bad:
            for sid in bad:
                text = next(i["text"] for i in items if i["id"] == sid)
                synthesize_scene(text, wavs[sid], args.voice, args.rate)
            durations = {sid: wav_duration(wav) for sid, wav in wavs.items()}
            sched, bad = schedule(items, durations)
        if bad:
            print("over scene limit even sped up:", file=sys.stderr)
            for row in sched:
                if row["id"] in bad:
                    print(f"  {row['id']}: ends {row['end']:.2f}s,"
                          f" limit {row['limit']:.2f}s", file=sys.stderr)
            return 1
    except subprocess.CalledProcessError as exc:
        print(f"synth failed: {exc.cmd}", file=sys.stderr)
        print(f"stderr:\n{exc.stderr}", file=sys.stderr)
        return 2
    clips = [(wavs[row["id"]], row["at"]) for row in sched]
    total = max(row["end"] for row in sched + [{"end": e} for _, e in final.values()])
    dst = mp4.parent / f"{mp4.stem}_narrated.mp4"
    srt = mp4.parent / f"{mp4.stem}_narration.srt"
    write_srt(sched, srt)
    try:
        subprocess.run(mix_cmd(mp4, clips, total, dst, not src_has_audio(mp4)),
                       check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        print(f"mix failed: {exc.cmd}", file=sys.stderr)
        print(f"stderr:\n{exc.stderr}", file=sys.stderr)
        return 2
    print(f"wrote {dst}")
    print(f"wrote {srt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
