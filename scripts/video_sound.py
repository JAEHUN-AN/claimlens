"""ffmpeg sound beds for the demo videos: voice clip + optional music."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

__all__ = [
    "ffmpeg_bin",
    "find_font",
    "have_ffmpeg",
    "mux_sound",
    "speed_filter",
    "speed_spans",
    "voice_at",
]


def ffmpeg_bin() -> str:
    return os.environ.get("CLAIMLENS_FFMPEG", "ffmpeg")


def have_ffmpeg() -> bool:
    return shutil.which(ffmpeg_bin()) is not None


def mux_sound(webm: Path, out_mp4: Path, total: float, voice=None, music=None) -> None:
    """Mux voice and/or music beds onto the silent webm. Raises on failure.

    voice: (wav_path, start_s, len_s). music: path or None. Music bed at
    -18 dB, ducked while the voice plays, fades in/out. apad keeps the
    output at video length when a bed is short. H.264 + AAC out.
    """
    lead = _leading_excess(webm, total)
    cmd: list[str] = [ffmpeg_bin(), "-y"]
    if lead > 0:
        # The recording starts when the browser context opens; page loads and server start-up
        # come before the first segment. Cut that lead so the video is exactly `total` long.
        cmd += ["-ss", f"{lead:.3f}"]
    cmd += ["-i", str(webm)]
    filters: list[str] = []
    maps = ["-map", "0:v"]
    if voice:
        wav, start, length = voice
        cmd += ["-i", str(wav)]
        delay_ms = int(start * 1000)
        filters.append(
            f"[1:a]atrim=0:{length},afade=t=in:st=0:d=0.5,"
            f"afade=t=out:st={length - 1.5}:d=1.5,"
            f"aresample=44100,adelay={delay_ms}:all=1[v]"
        )
    if music:
        cmd += ["-i", str(music)]
        idx = 2 if voice else 1
        vol = f"if(between(t,{voice[1]},{voice[1] + voice[2]}),0.03,0.126)" if voice else "0.126"
        filters.append(
            f"[{idx}:a]aresample=44100,volume='{vol}':eval=frame,"
            f"afade=t=in:st=0:d=2,afade=t=out:st={total - 3:.1f}:d=3[m]"
        )
    if voice and music:
        filters.append("[v][m]amix=inputs=2:duration=longest:dropout_transition=0[mix];[mix]apad[a]")
        maps += ["-map", "[a]"]
    elif voice:
        filters.append("[v]apad[a]")
        maps += ["-map", "[a]"]
    elif music:
        filters.append("[m]apad[a]")
        maps += ["-map", "[a]"]
    if filters:
        cmd += ["-filter_complex", ";".join(filters)]
    cmd += maps + ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "veryfast"]
    if filters:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-t", f"{total:.3f}"]
    cmd.append(str(out_mp4))
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _leading_excess(webm: Path, total: float) -> float:
    """Seconds of the recording before the first segment (duration minus the storyboard total)."""
    probe = shutil.which(ffmpeg_bin().replace("ffmpeg", "ffprobe")) or shutil.which("ffprobe")
    if not probe:
        return 0.0
    out = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(webm)],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    try:
        excess = float(out) - total
    except ValueError:
        return 0.0
    return excess if excess > 0.3 else 0.0


def voice_at(board: dict) -> float | None:
    """Start time of the segment flagged for the voice bed, if any."""
    elapsed = 0.0
    for seg in board["segments"]:
        if seg.get("sound") == "voice":
            return elapsed
        elapsed += seg["duration"]
    return None


def find_font() -> Path:
    """A drawtext font file; CLAIMLENS_FONT wins, then platform guesses."""
    override = os.environ.get("CLAIMLENS_FONT")
    candidates = [Path(override)] if override else []
    candidates += [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    tried = ", ".join(str(c) for c in candidates)
    raise RuntimeError(f"no drawtext font found (tried {tried}); set CLAIMLENS_FONT")


def _ff_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:")


def speed_filter(spans: list[tuple[float, float]], total: float, tag: Path, font: Path) -> str:
    """filter_complex: play spans 2x with a tag overlay, keep the rest.

    spans: (start, end) seconds on the recorded timeline, non-overlapping.
    Pure string building; raises on bad spans.
    """
    for start, end in spans:
        if not 0 <= start < end <= total:
            raise ValueError(f"bad speed span ({start}, {end}) for {total}s")
    cuts: list[tuple[float, float, bool]] = []
    cursor = 0.0
    for start, end in sorted(spans):
        if start < cursor:
            raise ValueError(f"overlapping speed spans near {start}")
        if start > cursor:
            cuts.append((cursor, start, False))
        cuts.append((start, end, True))
        cursor = end
    if cursor < total:
        cuts.append((cursor, total, False))
    font_esc = _ff_path(font)
    tag_esc = _ff_path(tag)
    parts = []
    for i, (start, end, sped) in enumerate(cuts):
        if sped:
            parts.append(
                f"[0:v]trim={start:.3f}:{end:.3f},setpts=(PTS-STARTPTS)/2,"
                f"drawtext=fontfile='{font_esc}':textfile='{tag_esc}':"
                f"fontsize=34:fontcolor=white:box=1:boxcolor=black@0.6:"
                f"x=w-text_w-24:y=24[v{i}]"
            )
        else:
            parts.append(f"[0:v]trim={start:.3f}:{end:.3f},setpts=PTS-STARTPTS[v{i}]")
    parts.append("".join(f"[v{i}]" for i in range(len(cuts))) + f"concat=n={len(cuts)}:v=1:a=0[v]")
    return ";".join(parts)


def speed_spans(webm: Path, spans: list[tuple[float, float]], total: float, out: Path,
                tag_text: str = "2×") -> float:
    """Rebuild the video with spans at 2x plus a tag. Returns the new length."""
    with tempfile.TemporaryDirectory() as tmp:
        tag = Path(tmp) / "tag.txt"
        tag.write_text(tag_text, encoding="utf-8")
        filt = speed_filter(spans, total, tag, find_font())
        cmd = [ffmpeg_bin(), "-y", "-i", str(webm), "-filter_complex", filt,
               "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-crf", "20", "-preset", "veryfast", "-an", str(out)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    return total - sum(end - start for start, end in spans) / 2
