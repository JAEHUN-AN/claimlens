"""Voice intake tests: cached transcripts, facts, and eligibility."""

import io
import json
import wave
from pathlib import Path

from claimlens.providers.replay import ReplayProvider
from claimlens.voice import intake, to_asr_wav, transcribe


def truth():
    path = Path("samples/scenarios_voice.json")
    return json.loads(path.read_text(encoding="utf-8"))["scenarios"][0]


def test_transcribe_replays_both_clips():
    en = transcribe("W_factory_fall_en", live=False)
    ko = transcribe("W_factory_fall_ko", live=False)
    assert "left wrist" in en["transcript"]
    assert "Anson" in en["transcript"]
    assert "손목" in ko["transcript"]
    assert "이십 일" in ko["transcript"]
    assert en["audio_duration_ms"] and ko["audio_duration_ms"]


def test_en_facts_match_truth():
    expected = truth()["expected"]
    result = intake("W_factory_fall_en", live=False, provider=ReplayProvider())
    facts = result["facts"]
    for key in ("visa", "korean_employer", "work_related", "incident_date", "body_part"):
        assert facts[key] == expected["facts"][key]
    for word in ("slipped", "stairs", "carrying", "box"):
        assert word in facts["mechanism"]
    assert result["eligibility"]["outcome"] == expected["nhi_status"]
    assert result["next_step"] == expected["next_step"]


def test_ko_facts_match_truth():
    expected = truth()["expected"]
    result = intake("W_factory_fall_ko", live=False, provider=ReplayProvider())
    facts = result["facts"]
    for key in ("visa", "korean_employer", "work_related", "incident_date", "body_part"):
        assert facts[key] == expected["facts"][key]
    for word in ("slipped", "stairs", "carrying", "box"):
        assert word in facts["mechanism"]
    assert result["eligibility"]["outcome"] == expected["nhi_status"]
    assert result["next_step"] == expected["next_step"]


def test_heard_facts_need_confirmation():
    for clip in ("W_factory_fall_en", "W_factory_fall_ko"):
        result = intake(clip, live=False, provider=ReplayProvider())
        assert set(result["to_confirm"]) == {"incident_date", "visa"}
        for field, entry in result["to_confirm"].items():
            assert entry["value"] == result["facts"][field]
            assert entry["quote"] == result["quotes"][field]
            assert entry["quote"] in result["transcript"]
        assert [c["field"] for c in result["confirmations"]] == ["incident_date", "visa"]
        assert result["confirmations"][0]["question"].startswith("I heard 20 October")
        assert result["confirmations"][1]["question"] == "I heard visa E-9 — is that right?"


def test_quotes_come_from_transcript():
    for clip in ("W_factory_fall_en", "W_factory_fall_ko"):
        result = intake(clip, live=False, provider=ReplayProvider())
        assert set(result["quotes"]) == set(result["facts"])
        for key, quote in result["quotes"].items():
            assert quote, f"empty quote for {key}"
            assert quote in result["transcript"], f"quote for {key} not in transcript"


def test_to_asr_wav_format():
    raw = Path("samples/audio/W_factory_fall_en.wav").read_bytes()
    converted = to_asr_wav(raw)
    with wave.open(io.BytesIO(converted), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 24000
        assert wav.getnframes() > 0
