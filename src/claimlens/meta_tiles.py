"""Built-with-Meta tiles: each tool's step plus one measured fact.

Facts are computed from repo data (git log, eval data files, caches,
masks on disk). A tile without a computable fact shows only its step —
never an invented figure. Shared by the demo section, the README model
table, and the video Meta card.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

STEPS = {
    "code": ("wrote the code from the backlog", "백로그대로 코드 작성"),
    "spark": ("reads documents, runs the agent", "서류 판독, 에이전트 실행"),
    "files": ("documents ride by file id", "파일 ID로 서류 전송"),
    "sam": ("masks seals and signatures", "인장·서명 마스킹"),
    "voice": ("spoken intake to confirmed facts", "음성 접수 후 사실 확인"),
    "open": ("open weights, measured side by side", "개방형 가중치 병행 측정"),
}
TOOLS = {
    "code": "Muse Code",
    "spark": "Muse Spark",
    "files": "Files API",
    "sam": "SAM 3.1",
    "voice": "Voice Transcribe",
    "open": "Spark Open on Baseten",
}


def _code_fact(root: Path) -> dict[str, str] | None:
    try:
        proc = subprocess.run(["git", "-c", "safe.directory=" + str(root),
                               "rev-list", "--count", "HEAD"],
                              check=False, capture_output=True, text=True, cwd=root,
                              timeout=30)
        count = int(proc.stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        count = 0
    if count > 0:
        return {"en": f"{count} commits", "ko": f"{count}개 커밋"}
    log = root / "docs" / "meta-tooling-log.md"
    if not log.exists():
        return None
    sessions = sum(1 for line in log.read_text(encoding="utf-8").splitlines()
                   if line.startswith("## "))
    return {"en": f"{sessions} logged sessions", "ko": f"기록된 작업 {sessions}건"}


def _spark_fact(root: Path) -> dict[str, str] | None:
    from claimlens import hard_eval

    files = sorted((root / "data").glob("hard_eval_*.json"))
    if not files:
        return None
    scored = agreed = agree_n = 0
    repeat = 0
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    for entry in data["sets"].values():
        cases = entry["cases"]
        repeat = len(cases[0]["runs"]) if cases else 0
        summary = hard_eval.summarize(cases, repeat)
        for acc in summary["accuracy"].values():
            scored += acc["n"]
        for agr in summary["agree"].values():
            agreed += agr["agree"]
            agree_n += agr["n"]
    if not scored or not agree_n:
        return None
    pct = round(agreed * 100 / agree_n)
    return {
        "en": f"{scored} fields read ×{repeat}, {pct}% run-to-run agreement",
        "ko": f"{scored}개 필드 ×{repeat}회 판독, 실행 간 일치율 {pct}%",
    }


def _files_fact(root: Path) -> dict[str, str] | None:
    path = root / "data" / "files_probe.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("files_api") != "works":
        return None
    tokens = data["tokens"]["total_tokens"]
    part = data["file_part"]
    return {
        "en": f"one read by file id as {part}, {tokens:,} tokens",
        "ko": f"파일 ID로 1회 판독({part}), {tokens:,} 토큰",
    }


def _sam_fact(root: Path) -> dict[str, str] | None:
    masked = sorted((root / "docs" / "masking").glob("*_after.png"))
    if not masked:
        return None
    return {
        "en": f"{len(masked)} masked copies",
        "ko": f"{len(masked)}건 마스킹본",
    }


def _voice_fact() -> dict[str, str]:
    from claimlens.voice import CONFIRM_FIELDS

    count = len(CONFIRM_FIELDS)
    return {
        "en": f"{count} fact types need confirmation",
        "ko": f"{count}종 사실 확인 필요",
    }


def _open_fact() -> dict[str, str] | None:
    from claimlens.eval import eval_all

    prev = os.environ.get("CLAIMLENS_PROVIDER")
    os.environ["CLAIMLENS_PROVIDER"] = "replay"
    try:
        rows = eval_all()
    except Exception:  # noqa: BLE001 - any miss means no computable fact
        return None
    finally:
        if prev is None:
            os.environ.pop("CLAIMLENS_PROVIDER", None)
        else:
            os.environ["CLAIMLENS_PROVIDER"] = prev
    matched = total = 0
    for row in rows:
        opened = row.get("open")
        if row.get("variant") != "photo" or not opened:
            continue
        for field in ("total", "lines", "checks"):
            total += 1
            matched += row.get(field) == opened.get(field)
    if not total:
        return None
    return {
        "en": f"{matched}/{total} fields match hosted",
        "ko": f"{total}개 중 {matched}개 일치",
    }


def tiles(root: Path) -> list[dict[str, Any]]:
    """Six tiles in video order; fact is None when not computable."""
    facts = {
        "code": _code_fact(root),
        "spark": _spark_fact(root),
        "files": _files_fact(root),
        "sam": _sam_fact(root),
        "voice": _voice_fact(),
        "open": _open_fact(),
    }
    out = []
    for key in ("code", "spark", "files", "sam", "voice", "open"):
        step_en, step_ko = STEPS[key]
        out.append({"tool": TOOLS[key], "key": key,
                    "step": {"en": step_en, "ko": step_ko},
                    "fact": facts[key]})
    return out


MODEL_ROWS = (
    ("Wrote the code from the backlog", "Muse Code (`muse-spark-1.3`)",
     ("Owner reviewed, ran live/engine calls where the Windows sandbox could not "
      "([tooling log](docs/meta-tooling-log.md))"), "code"),
    ("Send documents by file id", "Files API (`purpose=\"user_data\"`)",
     "Upload once per image, reference as `input_image`; base64 fallback", "files"),
    ("Read receipts + certificates", "`muse-spark-1.3` (hosted)",
     ("Decides the transcription: text, amounts, categories, dates, codes; "
      "strict schema, two images"), "spark"),
    ("Rephrase rationale drafts", "`muse-spark-1.3` (hosted)",
     "Decides wording only; amounts and clause IDs copied by code, checked", None),
    ("Translate Claim Pack row labels", "`muse-spark-1.3` (hosted)",
     "Decides label wording; amounts copied by code", None),
    ("Translate Claim Pack (Vietnamese)", "`muse-spark-1.3` (hosted)",
     "Decides labels + sentences; amounts, codes, dates copied by code", None),
    ("Clarifying agent loop", "`muse-spark-1.3` (hosted)",
     "Decides the next tool and when to ask; numbers only from tools, step cap 12",
     None),
    ("Transcribe spoken intake", "`muse-voice-transcribe-1.0` (hosted)",
     "Decides the transcript; dates/codes marked to confirm, never certain", "voice"),
    ("Extract facts from transcript", "`muse-spark-1.3` (hosted)",
     "Decides facts + supporting quotes; uncertain ones routed to confirm", "voice"),
    ("Compare documents (consistency)", "`muse-spark-1.3` (hosted)",
     "Decides mismatch findings from quoted evidence; code drops unquoted claims",
     None),
    ("Translate row labels (comparison)", "`meta-models/muse-spark-open-1026` (Baseten)",
     "Decides the same labels for comparison; forced `submit_labels` tool call", None),
    ("Read receipts + certificates (comparison)",
     "`meta-models/muse-spark-open-1026` (Baseten)",
     "Decides the same reading for comparison; forced `submit_reading` tool call", "open"),
    ("Mask seals and signatures", "`sam-3.1` (hosted)",
     "Decides seal/signature boxes; painted on a copy", "sam"),
)


def render_model_table(root: Path) -> str:
    """README model table with a Measured column from the tile facts."""
    facts = {tile["key"]: tile["fact"] for tile in tiles(root)}
    rows = ["| Step | Model | How | Measured |", "|---|---|---|---|"]
    for step, model, how, key in MODEL_ROWS:
        fact = facts[key] if key else None
        measured = fact["en"] if fact else "—"
        rows.append(f"| {step} | {model} | {how} | {measured} |")
    return "\n".join(rows) + "\n"
