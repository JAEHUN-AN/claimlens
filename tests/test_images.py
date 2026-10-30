"""Image size guards: refuse pixel bombs before decoding (S2)."""

import struct
from pathlib import Path

import pytest


def _bmp(path: Path, width: int, height: int) -> Path:
    """A header-only BMP: Pillow reads dimensions without pixel data."""
    row = ((width * 3 + 3) // 4) * 4
    size = 54 + row * height
    header = struct.pack("<2sIHHI", b"BM", size, 0, 0, 54)
    dib = struct.pack("<IiiHHIIIIII", 40, width, height, 1, 24, 0,
                      row * height, 0, 0, 0, 0)
    path.write_bytes(header + dib)
    return path


def test_check_refuses_huge_pixel_count(tmp_path):
    from claimlens.images import ImageTooLargeError, check_image_size

    huge = _bmp(tmp_path / "huge.bmp", 20000, 20000)
    with pytest.raises(ImageTooLargeError):
        check_image_size(huge)


def test_check_refuses_long_side(tmp_path):
    from claimlens.images import ImageTooLargeError, check_image_size

    wide = _bmp(tmp_path / "wide.bmp", 100, 13000)
    with pytest.raises(ImageTooLargeError):
        check_image_size(wide)


def test_check_accepts_normal_photo(tmp_path):
    from claimlens.images import check_image_size

    assert check_image_size(_bmp(tmp_path / "ok.bmp", 800, 600)) == (800, 600)


def test_prepare_image_refuses_before_decode(tmp_path):
    from claimlens.images import ImageTooLargeError
    from claimlens.providers.meta import prepare_image

    huge = _bmp(tmp_path / "huge.bmp", 20000, 20000)
    with pytest.raises(ImageTooLargeError):
        prepare_image(huge)


def test_probe_and_upright_refuse_before_decode(tmp_path):
    from claimlens.images import ImageTooLargeError
    from claimlens.rotation import prepare_probe_copy, upright_copy

    huge = _bmp(tmp_path / "huge.bmp", 20000, 20000)
    with pytest.raises(ImageTooLargeError):
        prepare_probe_copy(huge, tmp_path / "probe.jpg")
    with pytest.raises(ImageTooLargeError):
        upright_copy(huge, 90, tmp_path / "up.jpg")
