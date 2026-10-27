"""Muse Spark Open step over Baseten (backlog 11).

Chat Completions with tool calling (no JSON mode) on exactly
`meta-models/muse-spark-open-1026`. The model always reasons: the answer is
`message.content`, reasoning arrives separately in `message.reasoning_content`.
"""

import json
import os
from typing import Any

from dotenv import load_dotenv

from claimlens import cache as model_cache

MODEL = "meta-models/muse-spark-open-1026"
BASE_URL = "https://inference.baseten.co/v1"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "submit_labels",
            "description": "Submit English translations for Korean charge labels.",
            "parameters": {
                "type": "object",
                "properties": {
                    "labels": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"ko": {"type": "string"}, "en": {"type": "string"}},
                            "required": ["ko", "en"],
                        },
                    }
                },
                "required": ["labels"],
            },
        },
    }
]


def tool_schema() -> dict[str, Any]:
    return {"tools": TOOLS}


def translate_live(labels: list[str]) -> dict[str, Any]:
    """One tool-calling request; records arguments plus token usage."""
    from openai import OpenAI

    from claimlens.claimpack import LABELS_PREAMBLE

    load_dotenv()
    key = os.environ.get("BASETEN_API_KEY")
    if not key:
        raise RuntimeError("BASETEN_API_KEY is not set.")
    listed = "\n".join(f"- {label}" for label in labels)
    instructions = f"{LABELS_PREAMBLE}\nLabels:\n{listed}"
    client = OpenAI(base_url=BASE_URL, api_key=key)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": instructions}],
        tools=TOOLS,
        tool_choice={"type": "function", "function": {"name": "submit_labels"}},
    )
    message = response.choices[0].message
    calls = message.tool_calls or []
    if not calls:
        raise ValueError("Open model returned no tool call.")
    arguments = calls[0].function.arguments or "{}"
    usage = getattr(response, "usage", None)
    payload = {
        "model": MODEL,
        "instructions": instructions,
        "output_text": arguments,
        "reasoning_chars": len(getattr(message, "reasoning_content", None) or ""),
        "usage": {
            "input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            "reasoning_tokens": getattr(usage, "reasoning_tokens", 0) or 0,
        },
    }
    cache_key = model_cache.cache_key([], instructions, tool_schema(), MODEL)
    model_cache.store(cache_key, payload)
    payload["table"] = _table_of(arguments, labels)
    return payload


def translate_replay(labels: list[str]) -> dict[str, Any]:
    """Serve the recorded tool-call arguments; no key, no network."""
    from claimlens.claimpack import LABELS_PREAMBLE

    listed = "\n".join(f"- {label}" for label in labels)
    instructions = f"{LABELS_PREAMBLE}\nLabels:\n{listed}"
    cache_key = model_cache.cache_key([], instructions, tool_schema(), MODEL)
    payload = model_cache.load(cache_key)
    payload = dict(payload)
    payload["table"] = _table_of(payload.get("output_text", "{}"), labels)
    return payload


def translate_labels_open(labels: list[str]) -> dict[str, Any]:
    """Cached response first; records live only when missing."""
    load_dotenv()
    if os.environ.get("CLAIMLENS_PROVIDER", "meta").lower() == "replay":
        return translate_replay(labels)
    try:
        return translate_replay(labels)
    except LookupError:
        return translate_live(labels)


def _table_of(arguments: str, labels: list[str]) -> dict[str, str]:
    try:
        pairs = json.loads(arguments).get("labels", [])
    except ValueError as exc:
        raise ValueError(f"Open tool call was not JSON: {exc}.") from exc
    table = {p.get("ko", ""): p.get("en", "") for p in pairs if p.get("ko")}
    missing = [label for label in labels if label not in table]
    if missing:
        raise ValueError(f"Untranslated labels: {missing}.")
    return table
