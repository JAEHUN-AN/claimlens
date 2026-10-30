"""Image size guards: refuse pixel bombs before decoding (S2).

Dimensions come from the file header, so the check itself never
allocates the pixel buffer it protects against.
"""

from pathlib import Path

from PIL import Image
from PIL.Image import DecompressionBombError

# A 48 MP phone photo (8064x6048) still passes; anything past this is
# either hostile or a mistake, and would OOM the RGB working copies.
MAX_IMAGE_PIXELS = 50_000_000
MAX_IMAGE_SIDE = 12_000


class ImageTooLargeError(ValueError):
    """The image declares more pixels than any upload may carry."""


def check_image_size(path: Path) -> tuple[int, int]:
    """Header-only dimension check; raises ImageTooLargeError when over."""
    try:
        with Image.open(path) as img:
            width, height = img.size
    except DecompressionBombError as exc:
        raise ImageTooLargeError(f"{path.name} trips Pillow's own bomb fuse.") from exc
    if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE:
        raise ImageTooLargeError(
            f"{path.name} declares {width}x{height}; "
            f"sides are limited to {MAX_IMAGE_SIDE} px."
        )
    if width * height > MAX_IMAGE_PIXELS:
        raise ImageTooLargeError(
            f"{path.name} declares {width * height:,} pixels; "
            f"limited to {MAX_IMAGE_PIXELS:,}."
        )
    return width, height
