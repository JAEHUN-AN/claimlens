"""Rotation probe: a small separate call that asks how a page is turned.

A Korean bill photographed sideways comes back with two charge columns
swapped identically in both reads (sums unchanged, so checks and the
double read pass it). The reading schema, reading instructions, and
reader stay byte-identical -- rotation is asked separately per page on
a downscaled copy with its own prompt and cache key. When a page is
not upright, code rotates it upright (Pillow) and every read of that
page uses the upright copy.
"""

import tempfile
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, Field, TypeAdapter

from claimlens.cache import CacheMissError
from claimlens.schema import strict_schema_of

PROBE_LONG_SIDE = 768

ROTATION_INSTRUCTIONS = """You see one photo of a hospital document page. \
Report how the page is turned relative to upright, as a clockwise angle: \
0 means upright readable text; 90 means the page is turned 90 degrees \
clockwise; 180 means upside down; 270 means the page is turned 90 degrees \
counter-clockwise. Judge by the printed text lines, never by faces or \
background objects. Return only the rotation."""


class RotationProbe(BaseModel):
    rotation: Literal[0, 90, 180, 270] = Field(
        description="Clockwise angle of the page from upright."
    )


class ProbeError(RuntimeError):
    """The rotation probe failed; read the page as is and note it.

    missing is True only when a replay cache had no probe recording,
    so the caller can fall back to a live probe instead of giving up.
    """

    def __init__(self, message: str, *, missing: bool = False):
        super().__init__(message)
        self.missing = missing


def rotation_schema() -> dict[str, Any]:
    return strict_schema_of(RotationProbe)


def prepare_probe_copy(path: Path, dest: Path) -> bytes:
    """Downscale the long side to 768 px and save as JPEG; returns bytes."""
    from claimlens.images import check_image_size

    check_image_size(path)
    with Image.open(path) as img:
        small = img.convert("RGB")
        small.thumbnail((PROBE_LONG_SIDE, PROBE_LONG_SIDE), Image.LANCZOS)
        small.save(dest, format="JPEG", quality=85)
        return dest.read_bytes()


def probe_rotation(image: Path, provider: Any) -> int:
    """Ask one small call how the page is turned; raises ProbeError on failure."""
    try:
        with tempfile.TemporaryDirectory(prefix="rotation-probe-") as tmp:
            copy = Path(tmp) / "probe.jpg"
            prepare_probe_copy(image, copy)
            raw = provider.read_documents(
                [copy], ROTATION_INSTRUCTIONS, rotation_schema(),
                result_model=RotationProbe,
            )
        return TypeAdapter(RotationProbe).validate_python(raw).rotation
    except CacheMissError as exc:
        raise ProbeError(f"No probe recording for {image.name}.", missing=True) from exc
    except ProbeError:
        raise
    except Exception as exc:
        raise ProbeError(f"Rotation probe failed for {image.name}: {exc}") from exc


_CORRECTION = {
    90: Image.Transpose.ROTATE_90,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_270,
}


def upright_copy(path: Path, rotation: int, dest: Path) -> Path:
    """Rotate a turned page upright (Pillow); rotation is clockwise from upright."""
    from claimlens.images import check_image_size

    check_image_size(path)
    with Image.open(path) as img:
        img.transpose(_CORRECTION[rotation]).save(dest, format="JPEG", quality=90)
    return dest


FAILED_NOTE = "rotation probe failed; read as is"


def turned_note(rotation: int) -> str:
    return f"page turned {rotation} upright"


def upright_pages(
    paths: list[Path], provider: Any, tmpdir: Path
) -> tuple[list[Path], list[str]]:
    """Probe each page and return (paths to read, notes). Never raises ProbeError.

    Pages the probe calls turned are rotated upright into tmpdir (which
    must outlive the reads); probe failures keep the original page and
    are recorded as a note instead of blocking the read.
    """
    upright = list(paths)
    notes: list[str] = []
    for pos, path in enumerate(paths):
        try:
            rotation = probe_rotation(path, provider)
        except ProbeError:
            notes.append(FAILED_NOTE)
            continue
        if rotation:
            dest = tmpdir / f"upright_{pos}_{path.stem}.jpg"
            upright[pos] = upright_copy(path, rotation, dest)
            notes.append(turned_note(rotation))
    return upright, list(dict.fromkeys(notes))
