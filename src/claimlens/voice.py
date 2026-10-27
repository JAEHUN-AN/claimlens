"""Voice intake: transcribe a spoken report, then extract eligibility facts.

ASR answers only with a transcript (no usage block); Muse Spark extracts
strict facts from it, quoting the supporting words. Deterministic code maps
the facts to the eligibility rule.
"""

import io
import json
import os
import struct
import urllib.request
import uuid
import wave
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from claimlens.schema import strict_schema_of

ASR_URL = "https://api.meta.ai/v1/asr/transcribe"
ASR_MODEL = "muse-voice-transcribe-1.0"
ASR_RATE = 24000
VOICE_CACHE_DIR = "cache/voice"
NEXT_STEP = {"work_injury": "industrial accident compensation insurance first"}

FACTS_PREAMBLE = """Read the spoken incident report below and extract eligibility facts.
Today is 2026-10-27; resolve spoken dates against it as YYYY-MM-DD.
Normalize the visa code to its printed form (for example E-9).
Every quote_* field is required: copy the exact transcript words that
support the matching fact. Never leave a quote empty when the fact is set.
Report only; never give medical advice or guess a diagnosis."""


class VoiceFacts(BaseModel):
    visa: str = Field(description="Visa code, printed form, or empty.")
    korean_employer: bool = Field(description="True when working for a Korean employer.")
    work_related: bool = Field(description="True when hurt at work or on shift.")
    incident_date: str = Field(description="Incident date, YYYY-MM-DD, or empty.")
    body_part: str = Field(description="Injured body part in English, or empty.")
    mechanism: str = Field(description="How it happened, one short English phrase.")
    quote_visa: str = Field(description="Transcript words supporting visa.")
    quote_korean_employer: str = Field(description="Transcript words supporting korean_employer.")
    quote_work_related: str = Field(description="Transcript words supporting work_related.")
    quote_incident_date: str = Field(description="Transcript words supporting incident_date.")
    quote_body_part: str = Field(description="Transcript words supporting body_part.")
    quote_mechanism: str = Field(description="Transcript words supporting mechanism.")


def facts_schema() -> dict[str, Any]:
    return strict_schema_of(VoiceFacts)


def to_asr_wav(raw: bytes) -> bytes:
    """Convert any PCM WAV to mono s16le at 24000 Hz for the ASR endpoint."""
    with wave.open(io.BytesIO(raw), "rb") as src:
        channels, width, rate = src.getnchannels(), src.getsampwidth(), src.getframerate()
        count = src.getnframes()
        frames = src.readframes(count)
    fmt = {1: "b", 2: "h", 4: "i"}[width]
    samples = struct.unpack(f"<{count * channels}{fmt}", frames)
    if width == 1:
        samples = [s + 128 for s in samples]
    mono = [
        sum(samples[i * channels : (i + 1) * channels]) // channels if channels > 1 else samples[i]
        for i in range(count)
    ]
    scale = 32767 / 2147483647 if width == 4 else 32767 / 127 if width == 1 else 1
    mono = [int(s * scale) for s in mono]
    size = round(count * ASR_RATE / rate)
    resampled = [mono[min(count - 1, int(i * rate / ASR_RATE))] for i in range(size)]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(ASR_RATE)
        dst.writeframes(struct.pack(f"<{len(resampled)}h", *resampled))
    return buf.getvalue()


def voice_cache_path(clip: str) -> Path:
    return Path(VOICE_CACHE_DIR) / f"{clip}.json"


def transcribe(clip: str, live: bool) -> dict[str, Any]:
    """Transcribe samples/audio/<clip>.wav; the recording replays offline."""
    path = voice_cache_path(clip)
    if not live:
        if not path.exists():
            raise LookupError(f"No recorded transcript at {path}; run live once.")
        return json.loads(path.read_text(encoding="utf-8"))
    import dotenv

    dotenv.load_dotenv()
    api_key = os.environ.get("META_API_KEY")
    if not api_key:
        raise RuntimeError("META_API_KEY is not set; cannot transcribe live.")
    audio_dir = Path(os.environ.get("CLAIMLENS_SAMPLES_DIR", "samples")) / "audio"
    wav = to_asr_wav((audio_dir / f"{clip}.wav").read_bytes())
    request = {"model": ASR_MODEL, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="request"\r\n'
        f"Content-Type: application/json\r\n\r\n{json.dumps(request)}\r\n"
        f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="clip.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode() + wav + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        ASR_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"ASR {exc.code}: {detail}") from exc
    record = {
        "clip": clip,
        "model": ASR_MODEL,
        "transcript": payload.get("transcript", ""),
        "audio_duration_ms": payload.get("audioDurationMs"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def extract_facts(transcript: str, provider: Any) -> dict[str, Any]:
    """Strict facts plus per-fact quotes from one transcript."""
    return provider.write(
        f"{FACTS_PREAMBLE}\nReport:\n{transcript}", facts_schema(), VoiceFacts
    )


def facts_to_person(facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "visa": facts.get("visa", ""),
        "korean_employer": bool(facts.get("korean_employer", False)),
        "work_related": bool(facts.get("work_related", False)),
    }


def intake(clip: str, live: bool, provider: Any) -> dict[str, Any]:
    """Transcript, facts, eligibility, and next step for one clip."""
    from claimlens.eligibility import check_eligibility

    record = transcribe(clip, live)
    facts = extract_facts(record["transcript"], provider)
    eligibility = check_eligibility(facts_to_person(facts), facts.get("incident_date", ""))
    plain = {k: v for k, v in facts.items() if not k.startswith("quote_")}
    quotes = {k.removeprefix("quote_"): v for k, v in facts.items() if k.startswith("quote_")}
    return {
        "clip": clip,
        "transcript": record["transcript"],
        "audio_duration_ms": record.get("audio_duration_ms"),
        "facts": plain,
        "quotes": quotes,
        "eligibility": eligibility,
        "next_step": NEXT_STEP.get(eligibility["outcome"], ""),
    }
