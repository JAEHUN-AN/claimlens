"""Muse Spark Open steps over Baseten (backlog 11, 16).

Chat Completions with tool calling (no JSON mode) on exactly
`meta-models/muse-spark-open-1026`. The model always reasons: the answer is
`message.content`, reasoning arrives separately in `message.reasoning_content`.
"""

import base64
import json
import os
import time
from pathlib import Path
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


def reading_tools(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "submit_reading",
                "description": "Submit the receipt and certificate reading.",
                "parameters": schema,
            },
        }
    ]


def reading_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return {"tools": reading_tools(schema)}


class BasetenProvider:
    """Live Spark Open reads; same read_documents shape as MetaProvider."""

    name = "baseten"
    model = MODEL

    def __init__(self, api_key: str | None = None):
        load_dotenv()
        key = api_key or os.environ.get("BASETEN_API_KEY")
        if not key:
            raise RuntimeError("BASETEN_API_KEY is not set.")
        self._key = key
        self.calls: list[dict[str, Any]] = []

    def read_documents(
        self,
        images: list[Path],
        instructions: str,
        schema: dict[str, Any],
        result_model: Any = None,
    ) -> dict[str, Any]:
        from openai import OpenAI
        from pydantic import TypeAdapter

        from claimlens.providers.meta import prepare_image, unescape_json
        from claimlens.schema import ReadingResult

        load_dotenv()
        blobs = [prepare_image(p) for p in images]
        content: list[dict[str, Any]] = [{"type": "text", "text": instructions}]
        for blob in blobs:
            b64 = base64.b64encode(blob).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            )
        client = OpenAI(base_url=BASE_URL, api_key=self._key)
        started = time.perf_counter()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": content}],
            tools=reading_tools(schema),
            tool_choice={"type": "function", "function": {"name": "submit_reading"}},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        message = response.choices[0].message
        calls = message.tool_calls or []
        if not calls:
            raise ValueError("Open model returned no tool call.")
        arguments = calls[0].function.arguments or "{}"
        usage = getattr(response, "usage", None)
        in_tokens = getattr(usage, "prompt_tokens", 0) or 0
        out_tokens = getattr(usage, "completion_tokens", 0) or 0
        total = getattr(usage, "total_tokens", in_tokens + out_tokens) or 0
        reasoning = getattr(usage, "reasoning_tokens", 0) or 0
        payload = {
            "model": MODEL,
            "output_text": arguments,
            "reasoning_chars": len(getattr(message, "reasoning_content", None) or ""),
            "latency_ms": latency_ms,
            "usage": {
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "total_tokens": total,
                "reasoning_tokens": reasoning,
            },
        }
        key = model_cache.cache_key(blobs, instructions, reading_tool_schema(schema), MODEL)
        model_cache.store(key, payload)
        self.calls.append(
            {
                "model": MODEL,
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "total_tokens": total,
                "reasoning_tokens": reasoning,
                "latency_ms": latency_ms,
                "cost_usd": None,
            }
        )
        data = unescape_json(json.loads(arguments))
        model = result_model or ReadingResult
        return TypeAdapter(model).validate_python(data).model_dump(mode="json")


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
