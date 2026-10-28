"""Safe Files API probe: upload one image, read it once by file id.

Writes only to out/probe/ — never to cache/. Never run in the
sandbox (it needs the network); the owner runs it from a terminal.
"""

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any


def probe_files(
    image: Path | str, out_dir: Path | str, make_provider: Callable[[], Any]
) -> dict[str, Any]:
    """Upload + read once by file id; report method, tokens, and output."""
    from claimlens.prompts import READING_INSTRUCTIONS
    from claimlens.reader import reading_schema

    image = Path(image)
    if not image.is_file():
        raise ValueError(f"Not an image file: {image}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in list(out.glob("*.json")) + [out / "files_index.json"]:
        if stale.is_file():
            stale.unlink()
    old_cache = os.environ.get("CLAIMLENS_CACHE_DIR")
    os.environ["CLAIMLENS_CACHE_DIR"] = str(out)
    try:
        provider = make_provider()
        result = provider.read_documents([image], READING_INSTRUCTIONS, reading_schema())
        calls = [vars(c) for c in provider.calls]
    finally:
        if old_cache is None:
            os.environ.pop("CLAIMLENS_CACHE_DIR", None)
        else:
            os.environ["CLAIMLENS_CACHE_DIR"] = old_cache
    stored = sorted(out.glob("*.json"), key=lambda p: p.name)
    refs = json.loads(stored[0].read_text(encoding="utf-8")).get("input_refs", []) if stored else []
    method = refs[0].get("type", "?") if refs else "?"
    summary = {
        "files_api": "works" if method == "file" else "unavailable",
        "input": method,
        "tokens": calls[-1] if calls else {},
        "documents": len(result.get("documents", [])),
        "wrote": str(out),
    }
    (out / "probe_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
