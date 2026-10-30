"""Cover letter to the foreign insurer, drafted from the Claim Pack.

Spark writes prose only, with placeholders for every number, code,
date, currency, document name, and patient name. Any digit outside a
placeholder rejects the draft: one retry with a fixed feedback prompt,
then a code-only template. Code fills the placeholders from the pack,
then a final check rejects any number not in the pack. English only.
"""

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from claimlens.schema import strict_schema_of

PLACEHOLDERS = (
    "TOTAL",
    "CURRENCY",
    "VISIT_DATES",
    "DIAGNOSIS_CODES",
    "DOCUMENTS",
    "PATIENT_NAME",
)

# A letter draft is a short text-only call: no image, a few hundred
# tokens out. Stated flat allowance, like the re-read and probe ones.
LETTER_EST = 0.003

LETTER_PREAMBLE = """You draft a short English cover letter from a hospital Claim Pack \
for a foreign visitor's insurer. Write plain prose paragraphs only. For every \
number, code, date, currency, document name, and patient name, write ONLY its \
placeholder exactly as shown: {{TOTAL}}, {{CURRENCY}}, {{VISIT_DATES}}, \
{{DIAGNOSIS_CODES}}, {{DOCUMENTS}}, {{PATIENT_NAME}}. Never write any other \
digit, code, date, amount, or name: no digits at all outside the placeholders. \
Never invent facts. Never give medical advice. The patient writes this letter \
to their own insurer, in the first person ("I"), and signs it as {{PATIENT_NAME}}. \
Never write on behalf of the hospital, never sign as the hospital or any office, \
and ask the insurer to contact the patient with questions."""

LETTER_RETRY_NOTE = """The previous draft was rejected: it had digits or unknown \
placeholders outside the allowed six. Rewrite the letter with no digits at all \
except inside {{TOTAL}}, {{CURRENCY}}, {{VISIT_DATES}}, {{DIAGNOSIS_CODES}}, \
{{DOCUMENTS}}, {{PATIENT_NAME}}."""


class LetterDraft(BaseModel):
    letter: str = Field(description="Cover letter prose with placeholders only.")


class LetterRejected(ValueError):
    """A draft broke the placeholder contract, or a filled letter left the pack."""


def letter_schema() -> dict[str, Any]:
    return strict_schema_of(LetterDraft)


def letter_instructions(sample_id: str, variant: str) -> str:
    return (
        f"{LETTER_PREAMBLE}\nClaim: {sample_id} ({variant} documents). "
        "Draft the letter."
    )


def letter_retry_instructions(sample_id: str, variant: str) -> str:
    """Fixed feedback prompt: a retry is its own cache key, never an overwrite."""
    return (
        f"{LETTER_PREAMBLE}\n{LETTER_RETRY_NOTE}\n"
        f"Claim: {sample_id} ({variant} documents). Draft the letter."
    )


_PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_STRAY_RUN_RE = re.compile(r"\d[\d,]*")
_NUMBER_RE = re.compile(r"\d[\d,]*(\.\d+)?")


def check_draft(text: str) -> None:
    """Reject unknown placeholders and any digit outside placeholders."""
    unknown = sorted(set(_PLACEHOLDER_RE.findall(text)) - set(PLACEHOLDERS))
    if unknown:
        raise LetterRejected(f"Unknown placeholders: {unknown}.")
    stripped = _PLACEHOLDER_RE.sub("", text)
    stray = sorted(set(_STRAY_RUN_RE.findall(stripped)))
    if stray:
        raise LetterRejected(f"Digits outside placeholders: {stray}.")


def _normalize_number(raw: str) -> str:
    cleaned = raw.replace(",", "").lstrip("0")
    return cleaned or "0"


def pack_numbers(pack: dict[str, Any]) -> set[str]:
    """Numbers the pack itself carries: totals, dates, codes, identity digits."""
    visit = pack.get("visit") or {}
    codes = pack.get("codes") or {}
    cm = codes.get("cm") or {}
    patient = pack.get("patient") or {}
    facts = {
        "total": pack.get("total_krw"),
        "amounts": [i.get("amount") for i in pack.get("items", [])],
        "period": [visit.get("period_from"), visit.get("period_to")],
        "codes": [codes.get("kcd"), codes.get("who"), cm.get("chosen")],
        "identity": [
            patient.get("date_of_birth"),
            patient.get("passport"),
            patient.get("patient_id"),
        ],
    }
    text = json.dumps(facts, ensure_ascii=False, sort_keys=True)
    return {_normalize_number(m.group(0)) for m in _NUMBER_RE.finditer(text)}


CODE_SYSTEM_NAMES = ("ICD-10-CM", "ICD-10")


def check_letter_numbers(filled: str, pack: dict[str, Any]) -> None:
    """Reject any number in the filled letter that is not in the pack."""
    scanned = filled
    for name in CODE_SYSTEM_NAMES:
        scanned = scanned.replace(name, "")
    unknown = sorted(
        {_normalize_number(m.group(0)) for m in _NUMBER_RE.finditer(scanned)}
        - pack_numbers(pack)
    )
    if unknown:
        raise LetterRejected(f"Numbers not in the pack: {unknown}.")


def letter_values(pack: dict[str, Any]) -> dict[str, str]:
    """Placeholder values, every one copied from the pack by code."""
    visit = pack.get("visit") or {}
    codes = pack.get("codes") or {}
    cm = codes.get("cm") or {}
    total = pack.get("total_krw")
    return {
        "TOTAL": (
            f"{total:,}"
            if isinstance(total, (int, float)) and not isinstance(total, bool)
            else "-"
        ),
        # The pack covers Korean hospital bills, which are won-denominated.
        "CURRENCY": "KRW",
        "VISIT_DATES": f"{visit.get('period_from', '')} to {visit.get('period_to', '')}",
        # Code-system names carry digits (ICD-10); the number check
        # strips exactly these names before it looks for numbers.
        # Only the certificate's own code is stated as the patient's;
        # converted codes are marked rule-based candidates, not confirmed.
        "DIAGNOSIS_CODES": (
            f"{codes.get('kcd') or '-'} (KCD — the code on my certificate); "
            f"{codes.get('who') or '-'} (WHO ICD-10) and "
            f"{cm.get('chosen') or '-'} (ICD-10-CM) are rule-based candidates, "
            "not confirmed"
        ),
        # The pack is always built from the receipt and the certificate.
        "DOCUMENTS": "hospital receipt and medical certificate",
        "PATIENT_NAME": (pack.get("patient") or {}).get("name", ""),
    }


def fill_placeholders(text: str, values: dict[str, str]) -> str:
    for name, value in values.items():
        text = text.replace("{{" + name + "}}", value)
    return text


# Code-only fallback: prose with placeholders, no digits. Used when the
# draft is missing (replay before the owner records) or twice rejected.
TEMPLATE_LETTER = """Dear Claims Officer,

I am writing to file a claim for hospital treatment I received in Korea.

My name is {{PATIENT_NAME}}. I was treated from {{VISIT_DATES}}. The hospital \
bill totals {{TOTAL}} {{CURRENCY}}.

My diagnosis codes are {{DIAGNOSIS_CODES}}.

I enclose the following documents: {{DOCUMENTS}}.

Please let me know if you need anything else to process this claim.

Sincerely,
{{PATIENT_NAME}}"""


class _DraftFailed(Exception):
    """A draft attempt missed or broke the contract; retry or template next."""


def _try_draft(provider: Any, instructions: str) -> str:
    """One draft attempt; raises _DraftFailed instead of failing the run."""
    from claimlens.cache import CacheMissError

    try:
        draft = provider.write(instructions, letter_schema(), LetterDraft)
    except CacheMissError as exc:
        raise _DraftFailed(f"no recording: {exc}") from exc
    except Exception as exc:
        raise _DraftFailed(f"draft call failed: {exc}") from exc
    text = draft.get("letter") if isinstance(draft, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise _DraftFailed("empty draft")
    try:
        check_draft(text)
    except LetterRejected as exc:
        raise _DraftFailed(str(exc)) from exc
    return text


def build_letter(sample_id: str, variant: str, pack: dict[str, Any],
                 provider: Any) -> dict[str, Any]:
    """Draft (model), retry once, else template; fill and check (code).

    source is "spark" for a first-try draft, "spark-retry" for a
    recovered retry, "template" for the code-only fallback. The final
    numbers check raises LetterRejected; it never passes a rogue number.
    """
    values = letter_values(pack)
    try:
        text = _try_draft(provider, letter_instructions(sample_id, variant))
        source = "spark"
    except _DraftFailed:
        try:
            text = _try_draft(provider, letter_retry_instructions(sample_id, variant))
            source = "spark-retry"
        except _DraftFailed:
            text = TEMPLATE_LETTER
            source = "template"
    filled = fill_placeholders(text, values)
    check_letter_numbers(filled, pack)
    return {"sample": sample_id, "variant": variant, "text": filled, "source": source}


def draft_keys(sample_id: str, variant: str, model: str) -> dict[str, str]:
    """Cache keys for the base draft and its retry (new keys only)."""
    from claimlens.cache import cache_key

    schema = letter_schema()
    return {
        "base": cache_key([], letter_instructions(sample_id, variant), schema, model),
        "retry": cache_key(
            [], letter_retry_instructions(sample_id, variant), schema, model
        ),
    }


def plan_drafts(cases: list[tuple[str, str]], model: str) -> dict[str, Any]:
    """Recording plan; reads caches only, never the network."""
    from claimlens.cache import exists

    drafts = []
    for sample_id, variant in cases:
        keys = draft_keys(sample_id, variant, model)
        drafts.append(
            {
                "sample": sample_id,
                "variant": variant,
                "cached": exists(keys["base"]),
                "key": keys["base"][:12],
            }
        )
    missing = sum(not d["cached"] for d in drafts)
    return {"drafts": drafts, "missing": missing}


def record_drafts(cases: list[tuple[str, str]], provider_factory: Any) -> dict[str, Any]:
    """Record missing drafts under new keys; skips recorded ones, reports sources."""
    from claimlens.claimpack import build_pack
    from claimlens.providers.replay import ReplayProvider

    stored: list[str] = []
    sources: dict[str, str] = {}
    spent = 0.0
    for sample_id, variant in cases:
        provider = provider_factory()
        keys = draft_keys(sample_id, variant, provider.model)
        from claimlens.cache import exists

        if exists(keys["base"]):
            continue
        pack = build_pack(sample_id, variant, ReplayProvider())
        letter = build_letter(sample_id, variant, pack, provider)
        for call in provider.calls:
            spent += getattr(call, "cost_usd", None) or 0.0
        stored.append(f"{sample_id} {variant}")
        sources[f"{sample_id} {variant}"] = letter["source"]
    return {"stored": stored, "sources": sources, "spent": spent}
