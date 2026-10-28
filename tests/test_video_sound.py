"""ffmpeg sound mux for v2/vertical. Skipped when ffmpeg is missing."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import video_lib as V

pytestmark = pytest.mark.skipif(not V.have_ffmpeg(), reason="ffmpeg not on PATH")


def _make_fixtures(tmp_path: Path):
    root = Path(__file__).resolve().parent.parent
    ff = V.ffmpeg_bin()
    webm = tmp_path / "silent.webm"
    tone = tmp_path / "music.wav"
    subprocess.run(
        [ff, "-y", "-f", "lavfi", "-i", "testsrc=duration=12:size=320x240:rate=10",
         "-c:v", "libvpx", str(webm)],
        check=True, capture_output=True,
    )
    subprocess.run(
        [ff, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
         str(tone)],
        check=True, capture_output=True,
    )
    wav = root / "samples" / "audio" / "W_factory_fall_en.wav"
    assert wav.exists()
    return webm, tone, wav


def test_mux_voice_and_music(tmp_path):
    webm, tone, wav = _make_fixtures(tmp_path)
    out = tmp_path / "v2.mp4"
    V.mux_sound(webm, out, 12.0, voice=(wav, 2.0, 6.0), music=tone)
    assert out.exists() and out.stat().st_size > 0


def test_mux_music_only(tmp_path):
    webm, tone, _ = _make_fixtures(tmp_path)
    out = tmp_path / "vert.mp4"
    V.mux_sound(webm, out, 12.0, music=tone)
    assert out.exists() and out.stat().st_size > 0


def test_mux_silent_passthrough(tmp_path):
    webm, _, _ = _make_fixtures(tmp_path)
    out = tmp_path / "plain.mp4"
    V.mux_sound(webm, out, 12.0)
    assert out.exists() and out.stat().st_size > 0


def _duration(path: Path) -> float:
    proc = subprocess.run(
        [V.ffmpeg_bin(), "-i", str(path)],
        check=False, capture_output=True, text=True,
    )
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", proc.stderr)
    assert match, proc.stderr[-300:]
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def test_mux_lead_cut_keeps_total(tmp_path):
    webm, _, _ = _make_fixtures(tmp_path)
    out = tmp_path / "cut.mp4"
    V.mux_sound(webm, out, 8.0, lead=2.0)
    assert abs(_duration(out) - 8.0) < 0.2


def test_check_first_frame_matches_and_catches_mismatch(tmp_path):
    webm, _, _ = _make_fixtures(tmp_path)
    mp4 = tmp_path / "cut.mp4"
    V.mux_sound(webm, mp4, 8.0, lead=2.0)
    board = {"segments": [{"id": "first", "duration": 8.0}]}
    ref = tmp_path / "t-first_mid.png"
    V.extract_frame(mp4, 4.0, ref)
    assert V.check_first_frame(mp4, board, tmp_path, "t-") < 1.0
    from PIL import Image

    Image.new("RGB", (64, 36), (10, 200, 90)).save(ref)
    with pytest.raises(RuntimeError, match="does not match"):
        V.check_first_frame(mp4, board, tmp_path, "t-")
