"""ffmpeg sound beds for the demo videos: voice clip + optional music."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

__all__ = [
    "VOICE_LEN_S",
    "check_first_frame",
    "content_lead",
    "extract_frame",
    "ffmpeg_bin",
    "find_font",
    "have_ffmpeg",
    "mean_frame_diff",
    "mux_sound",
    "scale_filter",
    "speed_filter",
    "speed_spans",
    "voice_at",
]


# Seconds of the voice sample the main cut plays (mux_sound trims to this).
VOICE_LEN_S = 6.0


def ffmpeg_bin() -> str:
    return os.environ.get("CLAIMLENS_FFMPEG", "ffmpeg")


def have_ffmpeg() -> bool:
    return shutil.which(ffmpeg_bin()) is not None


def scale_filter(width: int, height: int) -> str:
    """Video filter: scale to width x height with lanczos resampling."""
    if width <= 0 or height <= 0:
        raise ValueError(f"bad scale target {width}x{height}")
    return f"scale={width}:{height}:flags=lanczos"


def mux_sound(webm: Path, out_mp4: Path, total: float, voice=None, music=None,
              lead: float | None = None, scale: tuple[int, int] | None = None) -> None:
    """Mux voice and/or music beds onto the silent webm. Raises on failure.

    voice: (wav_path, start_s, len_s). music: path or None. Music bed at
    -18 dB, ducked while the voice plays, fades in/out. apad keeps the
    output at video length when a bed is short. H.264 + AAC out.
    lead: measured pre-roll seconds (context creation to first segment);
    cut exactly that and keep `total`. None keeps the legacy full-length mux.
    scale: (width, height) to upscale in post (vertical: record 360x640,
    deliver 720x1280); None keeps the recorded size.
    """
    cmd: list[str] = [ffmpeg_bin(), "-y", "-i", str(webm)]
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
    if scale is not None:
        cmd += ["-vf", scale_filter(*scale)]
    if filters:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    else:
        cmd += ["-an"]
    if lead is not None:
        # Output seek: exact cut of the measured pre-roll (input -ss snaps
        # to keyframes), then keep exactly the storyboard length.
        cmd += ["-ss", f"{max(lead, 0.0):.3f}", "-t", f"{total:.3f}"]
    cmd.append(str(out_mp4))
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def voice_at(board: dict) -> float | None:
    """Start time of the segment flagged for the voice bed, if any."""
    elapsed = 0.0
    for seg in board["segments"]:
        if seg.get("sound") == "voice":
            return elapsed
        elapsed += seg["duration"]
    return None


def extract_frame(mp4: Path, at_s: float, out_png: Path) -> None:
    """Grab one frame from the finished mp4. Raises on failure."""
    cmd = [ffmpeg_bin(), "-y", "-ss", f"{at_s:.3f}", "-i", str(mp4),
           "-frames:v", "1", str(out_png)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def content_lead(webm: Path, ref_png: Path, ref_at: float, window_s: float = 30.0) -> float:
    """Legacy rescue: lead from the webm time best matching ref content.

    ref_png shows the recording at content time ref_at (a midpoint PNG).
    Scans 1 fps over the first window_s seconds and returns the best
    match minus ref_at. Good to ~1 s; the frame check still guards the cut.
    """
    with tempfile.TemporaryDirectory() as tmp:
        pattern = str(Path(tmp) / "scan%03d.png")
        cmd = [ffmpeg_bin(), "-y", "-i", str(webm), "-vf", "fps=1",
               "-t", f"{window_s:.0f}", pattern]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        frames = sorted(Path(tmp).glob("scan*.png"))
        if not frames:
            raise RuntimeError("lead scan produced no frames")
        best_diff, best = min((mean_frame_diff(frame, ref_png), i) for i, frame in enumerate(frames))
        print(f"lead scan: best frame {best}s diff {best_diff:.1f}")
        if best_diff > 40:
            raise RuntimeError("opening card not found in the webm; pass --lead SECONDS")
        return float(best) - ref_at


def mean_frame_diff(a: Path, b: Path, width: int = 320) -> float:
    """Mean absolute pixel difference (0-255) on downscaled grayscale.

    Downscaling desensitizes video compression noise while keeping
    scene-level differences (a wrong scene scores far above a right one).
    """
    from PIL import Image, ImageChops, ImageStat

    def small(path: Path) -> Image.Image:
        img = Image.open(path).convert("L")
        return img.resize((width, max(1, round(width * img.height / img.width))))
    diff = ImageChops.difference(small(a), small(b))
    return float(ImageStat.Stat(diff).mean[0])


def check_first_frame(mp4: Path, board: dict, out_dir: Path, png_prefix: str,
                      tol: float = 15.0) -> float:
    """The mp4 frame at the first segment's midpoint must match its PNG.

    Catches a misaligned lead trim (the frame would show a later scene).
    Returns the diff; raises when the reference PNG is missing or
    the diff exceeds tol.
    """
    seg = board["segments"][0]
    ref = out_dir / f"{png_prefix}{seg['id']}_mid.png"
    if not ref.is_file():
        raise RuntimeError(f"frame check needs the midpoint PNG: {ref}")
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "check.png"
        extract_frame(mp4, seg["duration"] / 2, frame)
        diff = mean_frame_diff(frame, ref)
    if diff > tol:
        raise RuntimeError(
            f"frame at {seg['duration'] / 2:.1f}s does not match {ref.name}: "
            f"diff {diff:.1f} > {tol} (lead trim misaligned?)"
        )
    return diff


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


def speed_filter(spans: list[tuple[float, float]], total: float, tag: Path, font: Path,
                 speed: int = 2) -> str:
    """filter_complex: play spans faster with a tag overlay, keep the rest.

    spans: (start, end) seconds on the recorded timeline, non-overlapping.
    Pure string building; raises on bad spans.
    """
    if speed < 2:
        raise ValueError(f"bad speed {speed}")
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
                f"[0:v]trim={start:.3f}:{end:.3f},setpts=(PTS-STARTPTS)/{speed},"
                f"drawtext=fontfile='{font_esc}':textfile='{tag_esc}':"
                f"fontsize=34:fontcolor=white:box=1:boxcolor=black@0.6:"
                f"x=w-text_w-24:y=24[v{i}]"
            )
        else:
            parts.append(f"[0:v]trim={start:.3f}:{end:.3f},setpts=PTS-STARTPTS[v{i}]")
    parts.append("".join(f"[v{i}]" for i in range(len(cuts))) + f"concat=n={len(cuts)}:v=1:a=0[v]")
    return ";".join(parts)


def speed_spans(webm: Path, spans: list[tuple[float, float]], total: float, out: Path,
                tag_text: str = "2×", speed: int = 2) -> float:
    """Rebuild the video with spans sped up plus a tag. Returns the new length."""
    with tempfile.TemporaryDirectory() as tmp:
        tag = Path(tmp) / "tag.txt"
        tag.write_text(tag_text, encoding="utf-8")
        filt = speed_filter(spans, total, tag, find_font(), speed)
        cmd = [ffmpeg_bin(), "-y", "-i", str(webm), "-filter_complex", filt,
               "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-crf", "20", "-preset", "veryfast", "-an", str(out)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    return total - sum(end - start for start, end in spans) * (1 - 1 / speed)
