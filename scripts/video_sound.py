"""ffmpeg sound beds for the demo videos: voice clip + optional music."""

import os
import shutil
import subprocess
from pathlib import Path

__all__ = ["ffmpeg_bin", "have_ffmpeg", "mux_sound", "voice_at"]


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
    if filters:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    else:
        cmd += ["-an"]
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
