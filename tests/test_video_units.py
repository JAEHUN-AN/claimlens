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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "video"))
import video_lib as V
import video_post as P
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


def test_speed_filter_honours_speed():
    filt = V.speed_filter([(10.0, 20.0)], 45.0, Path("t"), Path("f"), speed=4)
    assert "setpts=(PTS-STARTPTS)/4" in filt
    with pytest.raises(ValueError, match="bad speed"):
        V.speed_filter([(10.0, 20.0)], 45.0, Path("t"), Path("f"), speed=1)


def _rush_board():
    return {"segments": [{"id": "live", "duration": 15, "rush": {"first": 3, "last": 2}}]}


def _rush_actuals():
    return [("a", 2.0, 8.0), ("live", 8.0, 48.0), ("b", 48.0, 58.0)]


def test_pick_rush_skips_fitting_cut():
    assert V.pick_rush(_rush_board(), _rush_actuals(), 2.0, 56.0) is None
    assert V.pick_rush(_rush_board(), _rush_actuals(), 2.0, 55.6) is None


def test_pick_rush_prefers_2x_then_4x():
    plan = V.pick_rush(_rush_board(), _rush_actuals(), 2.0, 50.0)
    assert (plan["speed"], plan["tag"]) == (2, "2×")
    assert plan["span"] == (11.0, 46.0)
    plan = V.pick_rush(_rush_board(), _rush_actuals(), 2.0, 36.0)
    assert (plan["speed"], plan["tag"]) == (4, "4×")


def test_pick_rush_fails_when_16x_cannot_fit():
    with pytest.raises(RuntimeError, match="even 16x cannot fit"):
        V.pick_rush(_rush_board(), _rush_actuals(), 2.0, 20.0)
    with pytest.raises(RuntimeError, match="no rush window"):
        V.pick_rush({"segments": []}, _rush_actuals(), 2.0, 20.0)


def test_final_times_trims_lead_and_rush():
    spans = [(11.0, 46.0, 4)]
    assert V.final_times(_rush_actuals(), 2.0, spans) == [
        ("a", 0.0, 6.0),
        ("live", 6.0, 19.75),
        ("b", 19.75, 29.75),
    ]
    assert V.final_times(_rush_actuals(), 2.0, []) == [
        ("a", 0.0, 6.0),
        ("live", 6.0, 46.0),
        ("b", 46.0, 56.0),
    ]


def test_validate_catches_bad_rush(tmp_path):
    good = {"segments": [{"id": "s", "caption": "x", "duration": 15, "page": "demo",
                                   "rush": {"first": 3, "last": 2}}]}
    assert V.validate(tmp_path, good, {"demo": ""}, 190) == []
    bad = {"segments": [{"id": "s", "caption": "x", "duration": 15, "page": "demo",
                                  "rush": {"first": 10, "last": 10}}]}
    assert any("bad rush" in e for e in V.validate(tmp_path, bad, {"demo": ""}, 190))


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


def test_validate_press_needs_key(tmp_path):
    good = {"segments": [{"id": "s", "caption": "x", "duration": 5, "page": "demo",
                                    "actions": [{"op": "press", "key": "Escape"}]}]}
    assert V.validate(tmp_path, good, {"demo": ""}, 190) == []
    bad = {"segments": [{"id": "s", "caption": "x", "duration": 5, "page": "demo",
                                  "actions": [{"op": "press"}]}]}
    assert any("press needs a key" in e for e in V.validate(tmp_path, bad, {"demo": ""}, 190))


def test_actuals_roundtrip_and_garbage(tmp_path):
    path = tmp_path / "actuals.json"
    actuals = [("a", 1.5, 7.5), ("b", 7.5, 12.5)]
    P.save_actuals(path, actuals, 1.5, 12.0)
    assert P.load_actuals(path) == (actuals, 1.5, 12.0)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="bad actuals file"):
        P.load_actuals(path)


def test_actuals_from_timeline_stops_at_final_cut(tmp_path):
    timeline = tmp_path / "timeline.txt"
    timeline.write_text(
        "00:00:00.000 --> 00:00:06.000 a Cap a (planned 00:00:00.000 --> 00:00:06.000)\n"
        "00:00:06.000 --> 00:00:21.000 live Cap live (planned 00:00:06.000 --> 00:00:11.000)\n"
        "# final cut (lead trimmed, live wait rushed)\n"
        "00:00:00.000 --> 00:00:06.000 a Cap a\n",
        encoding="utf-8",
    )
    assert P.actuals_from_timeline(timeline) == [("a", 0.0, 6.0), ("live", 6.0, 21.0)]
    timeline.write_text("garbage\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bad timeline line"):
        P.actuals_from_timeline(timeline)


def test_resolve_post_inputs_prefers_saved_actuals(tmp_path):
    board = {"segments": [
        {"id": "a", "caption": "x", "duration": 6},
        {"id": "closing", "caption": "y", "duration": 6},
    ]}
    webm = tmp_path / "cut.webm"
    webm.write_bytes(b"fake")
    actuals = [("a", 2.0, 8.0), ("closing", 8.0, 14.0)]
    saved = tmp_path / "cut_actuals.json"
    P.save_actuals(saved, actuals, 2.0, 12.0)
    got_webm, got_actuals, got_lead = P.resolve_post_inputs(
        board, tmp_path, "cut.webm", "cut_actuals.json", "timeline.txt", "p-",
        None, None, None,
    )
    assert (got_webm, got_actuals, got_lead) == (webm, actuals, 2.0)


def test_resolve_post_inputs_recovers_from_timeline_with_lead(tmp_path):
    board = {"segments": [
        {"id": "a", "caption": "x", "duration": 6},
        {"id": "closing", "caption": "y", "duration": 6},
    ]}
    webm = tmp_path / "cut.webm"
    webm.write_bytes(b"fake")
    (tmp_path / "timeline.txt").write_text(
        "00:00:00.000 --> 00:00:06.000 a Cap a (planned 00:00:00.000 --> 00:00:06.000)\n"
        "00:00:06.000 --> 00:00:12.000 closing Cap b (planned 00:00:06.000 --> 00:00:12.000)\n",
        encoding="utf-8",
    )
    _, actuals, lead = P.resolve_post_inputs(
        board, tmp_path, "cut.webm", "missing_actuals.json", "timeline.txt", "p-",
        None, None, 2.5,
    )
    assert actuals == [("a", 0.0, 6.0), ("closing", 6.0, 12.0)]
    assert lead == 2.5


def test_resolve_post_inputs_rejects_id_mismatch(tmp_path):
    board = {"segments": [{"id": "a", "caption": "x", "duration": 6}]}
    webm = tmp_path / "cut.webm"
    webm.write_bytes(b"fake")
    saved = tmp_path / "cut_actuals.json"
    P.save_actuals(saved, [("zzz", 0.0, 6.0)], 0.0, 6.0)
    with pytest.raises(ValueError, match="actuals cover"):
        P.resolve_post_inputs(board, tmp_path, "cut.webm", "cut_actuals.json",
                              "timeline.txt", "p-", None, None, None)


def test_run_post_prints_full_ffmpeg_error(monkeypatch, tmp_path, capsys):
    def boom(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, "", "full-stderr-here")

    monkeypatch.setattr(VS, "have_ffmpeg", lambda: True)
    monkeypatch.setattr(VS.subprocess, "run", boom)
    board = {"segments": [
        {"id": "a", "caption": "x", "duration": 6},
        {"id": "closing", "caption": "y", "duration": 6},
    ]}
    webm = tmp_path / "cut.webm"
    webm.write_bytes(b"fake")
    actuals = [("a", 0.0, 6.0), ("closing", 6.0, 12.0)]
    code = P.run_post(board, tmp_path, webm, actuals, 0.0, 12.0, None, "p-",
                      "timeline.txt", 12.0)
    assert code == 2
    err = capsys.readouterr().err
    assert "command:" in err and "full-stderr-here" in err


class _FakePage:
    def __init__(self):
        self.shots: list[str] = []

    def goto(self, url):
        pass

    def wait_for_load_state(self, state):
        pass

    def evaluate(self, expr, arg=None):
        return True

    def screenshot(self, path):
        self.shots.append(path)
        Path(path).write_bytes(b"png")


def _end_seconds(line: str) -> float:
    end = line.split(" --> ")[1].split()[0]
    hours, minutes, seconds = end.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def test_timeline_shows_actual_starts(tmp_path):
    board = {
        "segments": [
            {"id": "a", "caption": "Cap a", "duration": 0.2, "page": "demo",
             "actions": [{"op": "hold", "seconds": 0.5}]},
            {"id": "b", "caption": "Cap b", "duration": 0.2, "page": "demo", "actions": []},
        ]
    }
    V.run_segments(_FakePage(), board, {"demo": "http://x/"}, tmp_path, [""])
    lines = (tmp_path / "timeline.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("00:00:00.000 --> ")
    assert _end_seconds(lines[0]) >= 0.45
    assert "(planned 00:00:00.000 --> 00:00:00.200)" in lines[0]
    next_start = lines[1].split(" --> ")[0]
    hours, minutes, seconds = next_start.split(":")
    start_b = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    assert abs(start_b - _end_seconds(lines[0])) < 0.05


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


def test_scale_filter_pins_lanczos():
    assert V.scale_filter(720, 1280) == "scale=720:1280:flags=lanczos"
    with pytest.raises(ValueError, match="bad scale target"):
        V.scale_filter(0, 1280)


def test_mux_sound_upscales_only_when_asked(monkeypatch, tmp_path):
    cmds = []

    def fake_run(cmd, **kwargs):
        cmds.append(cmd)

    monkeypatch.setattr(VS.subprocess, "run", fake_run)
    webm = tmp_path / "in.webm"
    webm.write_bytes(b"fake")
    V.mux_sound(webm, tmp_path / "out.mp4", 45.0, scale=(720, 1280))
    assert "-vf" in cmds[0]
    assert cmds[0][cmds[0].index("-vf") + 1] == "scale=720:1280:flags=lanczos"
    V.mux_sound(webm, tmp_path / "out2.mp4", 45.0)
    assert "-vf" not in cmds[1]


def test_vertical_records_viewport_size_upscales_in_post():
    import record_vertical as RV

    assert (RV.VIEWPORT_W, RV.VIEWPORT_H) == (360, 640)
    assert (RV.RECORD_W, RV.RECORD_H) == (360, 640)
    assert (RV.RECORD_W, RV.RECORD_H) == (RV.VIEWPORT_W, RV.VIEWPORT_H)
    assert (RV.OUTPUT_W, RV.OUTPUT_H) == (720, 1280)


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
