"""narrate.py unit tests (63.2): fake synth, scheduling, SRT, ffmpeg assembly."""

import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "video"))

import narrate
import video_sound

ROOT = Path(__file__).resolve().parent.parent

TIMELINE = """00:00:01.000 --> 00:00:07.000 a First
00:00:07.000 --> 00:00:12.000 b Second
# final cut (lead trimmed, live wait rushed)
00:00:00.000 --> 00:00:06.000 a First
00:00:06.000 --> 00:00:11.000 b Second
"""

BOARD = {"segments": [
    {"id": "a", "caption": "A", "narration": "Alpha bravo.", "duration": 6,
     "page": "demo", "actions": []},
    {"id": "b", "caption": "B", "narration": "Charlie delta.", "duration": 5,
     "page": "demo", "actions": []},
    {"id": "ch", "caption": "1", "duration": 1, "page": "demo", "actions": []},
]}


def _fake_wav(path, seconds, rate=44100):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * frames)


def _fake_synth_factory(durations, calls):
    def fake(text, wav_path, voice, rate=None):
        calls.append((wav_path.stem, voice, rate))
        dur = durations[wav_path.stem]
        if rate is not None:
            dur = dur / 1.25
        _fake_wav(wav_path, dur)

    return fake


def _write_inputs(tmp_path):
    board_path = tmp_path / "board.json"
    board_path.write_text(json.dumps(BOARD), encoding="utf-8")
    timeline = tmp_path / "timeline.txt"
    timeline.write_text(TIMELINE, encoding="utf-8")
    mp4 = tmp_path / "cut_v3.mp4"
    mp4.write_bytes(b"fake")
    return board_path, timeline, mp4


def _patch_env(monkeypatch, sounded=True):
    monkeypatch.setattr(narrate.shutil, "which", lambda cmd: "/bin/" + cmd)
    monkeypatch.setattr(video_sound, "have_ffmpeg", lambda: True)
    monkeypatch.setattr(narrate, "src_has_audio", lambda mp4: sounded)


def test_parse_final_cut_reads_appendix(tmp_path):
    timeline = tmp_path / "timeline.txt"
    timeline.write_text(TIMELINE, encoding="utf-8")
    assert narrate.parse_final_cut(timeline) == {"a": (0.0, 6.0), "b": (6.0, 11.0)}


def test_parse_final_cut_rejects_garbage(tmp_path):
    timeline = tmp_path / "timeline.txt"
    timeline.write_text("00:00:01.000 --> 00:00:07.000 a First\n", encoding="utf-8")
    try:
        narrate.parse_final_cut(timeline)
    except ValueError as exc:
        assert "final-cut" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_build_items_skips_chapters_and_offsets_voice():
    final = {"a": (0.0, 6.0), "v": (6.0, 15.0)}
    board = {"segments": [
        {"id": "a", "narration": "Alpha.", "duration": 6},
        {"id": "ch", "caption": "1", "duration": 1},
        {"id": "v", "narration": "Voice.", "duration": 9, "sound": "voice"},
    ]}
    items = narrate.build_items(board, final, 6.0)
    assert [(i["id"], i["start"], i["limit"]) for i in items] == [
        ("a", 0.0, 6.3), ("v", 12.0, 15.3)]
    try:
        narrate.build_items({"segments": [{"id": "x", "narration": "X"}]}, {}, 0.0)
    except ValueError as exc:
        assert "final cut" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_schedule_chains_and_flags_overruns():
    items = [{"id": "a", "text": "A", "start": 0.0, "limit": 6.3},
             {"id": "b", "text": "B", "start": 6.0, "limit": 11.3}]
    sched, bad = narrate.schedule(items, {"a": 5.0, "b": 4.0})
    assert [(r["id"], r["at"], r["end"], r["ok"]) for r in sched] == [
        ("a", 0.0, 5.0, True), ("b", 6.0, 10.0, True)]
    assert bad == []
    sched, bad = narrate.schedule(items, {"a": 7.0, "b": 4.0})
    assert bad == ["a"]
    assert sched[1]["at"] == 7.25  # chained right after the long take


def test_write_srt_formats_cues(tmp_path):
    srt = tmp_path / "cut_narration.srt"
    narrate.write_srt([{"id": "a", "text": "Alpha bravo.", "at": 0.0, "end": 5.0},
                       {"id": "b", "text": "Charlie.", "at": 6.0, "end": 10.5}], srt)
    assert srt.read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:05,000\nAlpha bravo.\n"
        "\n2\n00:00:06,000 --> 00:00:10,500\nCharlie.\n")


def test_synth_cmd_uses_uvx_and_optional_rate(tmp_path):
    cmd = narrate.synth_cmd("Hi.", tmp_path / "a.mp3", "en-US-AndrewNeural")
    assert cmd[:3] == ["uvx", "--from", "edge-tts@latest"]
    assert "--rate" not in cmd
    cmd = narrate.synth_cmd("Hi.", tmp_path / "a.mp3", "en-US-AndrewNeural",
                            "+25%")
    assert cmd[-2:] == ["--rate", "+25%"]
    assert narrate.rate_ok("+25%") and narrate.rate_ok("-10%")
    assert not narrate.rate_ok("fast")


def test_mix_cmd_sounded_and_silent(tmp_path):
    clips = [(tmp_path / "a.wav", 0.0), (tmp_path / "b.wav", 6.0)]
    cmd = narrate.mix_cmd(tmp_path / "cut.mp4", clips, 11.0,
                          tmp_path / "cut_narrated.mp4", silent=False)
    joined = " ".join(cmd)
    assert "[0:a]" in joined and "anullsrc" not in joined
    assert "adelay=0|0" in joined and "adelay=6000|6000" in joined
    assert cmd[-8:-1] == ["-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                          "-shortest"]
    assert str(clips[0][0]) in cmd and str(clips[1][0]) in cmd
    cmd = narrate.mix_cmd(tmp_path / "cut.mp4", clips, 11.0,
                          tmp_path / "cut_narrated.mp4", silent=True)
    joined = " ".join(cmd)
    assert "anullsrc" in joined and "[1:a]" in joined
    try:
        narrate.mix_cmd(tmp_path / "cut.mp4", [], 11.0, tmp_path / "o.mp4", False)
    except ValueError as exc:
        assert "no narration clips" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_src_has_audio_sniffs_ffmpeg_stderr(monkeypatch):
    class Proc:
        stderr = "  Stream #0:1: Audio: aac (LC)"

    monkeypatch.setattr(narrate.subprocess, "run", lambda *a, **k: Proc())
    assert narrate.src_has_audio(Path("cut.mp4")) is True

    class Quiet:
        stderr = "  Stream #0:0: Video: h264"

    monkeypatch.setattr(narrate.subprocess, "run", lambda *a, **k: Quiet())
    assert narrate.src_has_audio(Path("cut.mp4")) is False


def _run_main(monkeypatch, tmp_path, durations, sounded=True):
    board_path, timeline, mp4 = _write_inputs(tmp_path)
    calls = []
    monkeypatch.setattr(narrate, "synthesize_scene",
                        _fake_synth_factory(durations, calls))
    _patch_env(monkeypatch, sounded)
    mixed = []
    monkeypatch.setattr(narrate.subprocess, "run",
                        lambda cmd, **k: mixed.append(cmd))
    out_dir = tmp_path / "narration"
    code = narrate.main(["--storyboard", str(board_path),
                         "--timeline", str(timeline), "--mp4", str(mp4),
                         "--out-dir", str(out_dir)])
    return code, calls, mixed, mp4


def test_main_fitting_flow_mixes_sounded(monkeypatch, tmp_path):
    code, calls, mixed, mp4 = _run_main(monkeypatch, tmp_path,
                                        {"a": 5.0, "b": 4.0})
    assert code == 0
    assert [(sid, rate) for sid, _, rate in calls] == [("a", None), ("b", None)]
    assert len(mixed) == 1
    assert "anullsrc" not in " ".join(mixed[0])
    assert mixed[0][-1].endswith("cut_v3_narrated.mp4")
    srt = mp4.parent / "cut_v3_narration.srt"
    assert "Alpha bravo." in srt.read_text(encoding="utf-8")


def test_main_retries_overruns_faster(monkeypatch, tmp_path):
    code, calls, mixed, _ = _run_main(monkeypatch, tmp_path,
                                      {"a": 7.0, "b": 4.0})
    assert code == 0
    assert ("a", "en-US-AndrewNeural", "+25%") in calls
    assert len(mixed) == 1


def test_main_fails_loudly_when_still_over(monkeypatch, tmp_path):
    code, _, mixed, mp4 = _run_main(monkeypatch, tmp_path,
                                    {"a": 9.0, "b": 4.0})
    assert code == 1
    assert mixed == []
    assert not (mp4.parent / "cut_v3_narration.srt").exists()


def test_main_silent_cut_gets_silence_bed(monkeypatch, tmp_path):
    code, _, mixed, _ = _run_main(monkeypatch, tmp_path,
                                  {"a": 5.0, "b": 4.0}, sounded=False)
    assert code == 0
    assert "anullsrc" in " ".join(mixed[0])


def test_main_rejects_bad_rate_and_missing_parts(monkeypatch, tmp_path):
    board_path, timeline, mp4 = _write_inputs(tmp_path)
    _patch_env(monkeypatch)
    assert narrate.main(["--storyboard", str(board_path), "--timeline",
                         str(timeline), "--mp4", str(mp4),
                         "--rate", "fast"]) == 2
    empty = tmp_path / "empty.json"
    empty.write_text('{"segments": [{"id": "ch", "caption": "1"}]}',
                     encoding="utf-8")
    assert narrate.main(["--storyboard", str(empty), "--timeline",
                         str(timeline), "--mp4", str(mp4)]) == 2


def test_spoken_turns_symbols_dates_and_links_into_speech():
    import narrate

    assert narrate.spoken("₩251.2 billion unclaimed in 2022 (est.)") == (
        "251.2 billion won unclaimed in 2022 (estimated)")
    assert narrate.spoken("takes 30+ minutes") == "takes 30 plus minutes"
    assert narrate.spoken("scorecard 8/8 — done") == "scorecard 8 of 8, done"
    assert narrate.spoken("Single read (2026-10-28, old pipeline) let 47") == (
        "Single read (old pipeline) let 47")
    assert narrate.spoken("T4 (needs_manual_check)") == "T4 (needs manual check)"
    assert narrate.spoken("Synthetic. Try it: a.io/b · c.com/d") == (
        "Synthetic. Try it at the links on screen.")


def test_before_after_and_gate_narration_come_from_data():
    import captions

    wanted = captions._wanted(captions.ROOT)
    narration = wanted["before_after"][1]
    assert "30+ minutes per claim (builder's estimate)" in narration
    assert "(measured)" in narration
    gate = wanted["gate"][1]
    assert gate.startswith("A single read on the old pipeline let ")
    assert "Real trips:" in gate
