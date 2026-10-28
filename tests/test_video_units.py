"""Pure unit tests for the v3 video machinery (no browser, no ffmpeg).

The live-server subprocess test needs listen(), like the serve tests.
"""

import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import video_lib as V
import video_sound as VS

ROOT = Path(__file__).resolve().parent.parent


def test_effective_total_counts_sped_segments():
    board = {"segments": [{"duration": 4}, {"duration": 24, "speed": 2}, {"duration": 10}]}
    assert V.effective_total(board) == 26.0
    assert V.effective_total({"segments": [{"duration": 5}]}) == 5.0


def test_speed_filter_tags_only_spans():
    filt = V.speed_filter([(10.0, 20.0)], 45.0, Path("tag.txt"), Path("font.ttf"))
    assert filt.count("drawtext") == 1
    assert "setpts=(PTS-STARTPTS)/2" in filt
    assert "trim=10.000:20.000" in filt
    assert "concat=n=3:v=1:a=0[v]" in filt


def test_speed_filter_rejects_bad_spans():
    with pytest.raises(ValueError, match="bad speed span"):
        V.speed_filter([(20.0, 10.0)], 45.0, Path("t"), Path("f"))
    with pytest.raises(ValueError, match="overlapping"):
        V.speed_filter([(5.0, 15.0), (10.0, 20.0)], 45.0, Path("t"), Path("f"))


def test_drop_payload_encodes_images(tmp_path):
    img = tmp_path / "shot.jpg"
    img.write_bytes(b"\xff\xd8\xffdata")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    payload = V.drop_payload(tmp_path, ["shot.jpg"])
    assert payload[0]["name"] == "shot.jpg"
    assert payload[0]["type"] == "image/jpeg"
    assert payload[0]["data"]
    with pytest.raises(ValueError, match="needs an image"):
        V.drop_payload(tmp_path, ["note.txt"])
    with pytest.raises(FileNotFoundError):
        V.drop_payload(tmp_path, ["missing.jpg"])


def test_uses_live():
    assert V.uses_live({"segments": [{"page": "live"}]}) is True
    assert V.uses_live({"segments": [{"page": "demo", "actions": [{"op": "goto", "page": "live"}]}]}) is True
    assert V.uses_live({"segments": [{"page": "demo"}]}) is False


def test_validate_catches_missing_drop_file(tmp_path):
    board = {
        "segments": [
            {
                "id": "live",
                "caption": "x",
                "duration": 5,
                "page": "demo",
                "actions": [{"op": "dropfiles", "selector": "#flow-drop", "files": ["nope.jpg"]}],
            }
        ]
    }
    errors = V.validate(tmp_path, board, {"demo": "flow-drop"}, 190)
    assert any("drop file missing" in e for e in errors)


def test_validate_catches_bad_speed(tmp_path):
    board = {"segments": [{"id": "s", "caption": "x", "duration": 5, "page": "demo", "speed": 1}]}
    errors = V.validate(tmp_path, board, {"demo": ""}, 190)
    assert any("bad speed" in e for e in errors)


def _can_listen() -> bool:
    try:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        sock.close()
    except OSError:
        return False
    return True


def test_mux_sound_cuts_measured_lead(monkeypatch, tmp_path):
    cmds = []

    def fake_run(cmd, **kwargs):
        cmds.append(cmd)

    monkeypatch.setattr(VS.subprocess, "run", fake_run)
    webm = tmp_path / "in.webm"
    webm.write_bytes(b"fake")
    V.mux_sound(webm, tmp_path / "out.mp4", 180.0, lead=1.234)
    assert cmds[0][-5:-2] == ["-ss", "1.234", "-t"]
    assert cmds[0][-1].endswith("out.mp4")
    assert cmds[0][-2] == "180.000"


def test_mux_sound_legacy_without_lead(monkeypatch, tmp_path):
    cmds = []

    def fake_run(cmd, **kwargs):
        cmds.append(cmd)

    monkeypatch.setattr(VS.subprocess, "run", fake_run)
    webm = tmp_path / "in.webm"
    webm.write_bytes(b"fake")
    V.mux_sound(webm, tmp_path / "out.mp4", 180.0)
    assert "-ss" not in cmds[0]
    assert "-t" not in cmds[0]


def test_mean_frame_diff_same_and_different(tmp_path):
    from PIL import Image

    same_a = tmp_path / "a.png"
    same_b = tmp_path / "b.png"
    img = Image.new("RGB", (64, 36), (200, 30, 30))
    img.save(same_a)
    img.save(same_b)
    assert V.mean_frame_diff(same_a, same_b) == 0.0
    white = tmp_path / "w.png"
    black = tmp_path / "k.png"
    Image.new("RGB", (64, 36), (255, 255, 255)).save(white)
    Image.new("RGB", (64, 36), (0, 0, 0)).save(black)
    assert V.mean_frame_diff(white, black) == 255.0


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_zoom_fit_clamp():
    proc = subprocess.run(
        ["node", "tests/video_zoom_check.mjs"],
        check=False,
        cwd=str(ROOT).removeprefix("\\\\?\\"),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "zoom fit: OK" in proc.stdout


@pytest.mark.skipif(not _can_listen(), reason="sandbox blocks listen()")
def test_start_live_server_answers_health():
    proc, base = V.start_live_server(ROOT)
    try:
        with urllib.request.urlopen(base + "/api/health", timeout=10) as resp:
            assert resp.status == 200
        with urllib.request.urlopen(base + "/docs/demo.html", timeout=10) as resp:
            assert resp.status == 200
    finally:
        proc.terminate()
