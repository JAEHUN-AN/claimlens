"""High-level reading: sample folders, provider selection, one entry point."""

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from claimlens.prompts import READING_INSTRUCTIONS
from claimlens.providers import Provider
from claimlens.schema import ReadingResult, strict_schema_of


def resolve_sample_images(sample_dir: Path, variant: str) -> list[Path]:
    """Receipt first, then medical certificate, for the given variant."""
    ordered = []
    for stem in ("receipt", "medical_certificate"):
        matches = sorted(sample_dir.glob(f"{stem}_{variant}.*"))
        if not matches:
            raise FileNotFoundError(f"No {stem}_{variant} image in {sample_dir}")
        ordered.append(matches[0])
    return ordered


def get_provider() -> Provider:
    load_dotenv()
    which = os.environ.get("CLAIMLENS_PROVIDER", "meta").lower()
    if which == "replay":
        from claimlens.providers.replay import ReplayProvider

        return ReplayProvider()
    from claimlens.providers.meta import MetaProvider

    return MetaProvider()


def reading_schema() -> dict[str, Any]:
    return strict_schema_of(ReadingResult)


def read_sample(sample_dir: Path | str, variant: str = "photo") -> dict[str, Any]:
    sample_dir = Path(sample_dir)
    images = resolve_sample_images(sample_dir, variant)
    provider = get_provider()
    result = provider.read_documents(images, READING_INSTRUCTIONS, reading_schema())
    calls = [vars(c) for c in getattr(provider, "calls", [])]
    return {
        "sample": sample_dir.name,
        "variant": variant,
        "images": [p.name for p in images],
        "provider": provider.name,
        "model": provider.model,
        "result": result,
        "calls": calls,
    }
