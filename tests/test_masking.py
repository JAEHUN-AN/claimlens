"""Masking tests: parser and drawing are pure; replay pins live SAM boxes."""

from PIL import Image

from claimlens.masking import mask_image, mask_sample_image, parse_sam_boxes

KV_TAG = "<|box;x1=903;y1=778;x2=1008;y2=804;w=1280;h=972|>"
BARE_TAG = "<|box;10;20;110;120;200;100|>"


def test_parse_key_value_boxes():
    boxes = parse_sam_boxes(f"pre {KV_TAG} mid {BARE_TAG} post")
    assert len(boxes) == 2
    assert boxes[0] == {"x1": 903.0, "y1": 778.0, "x2": 1008.0, "y2": 804.0, "w": 1280.0, "h": 972.0}
    assert boxes[1]["w"] == 200.0


def test_parse_ignores_text_without_boxes():
    assert parse_sam_boxes("nothing found here") == []
    assert parse_sam_boxes("<|box;x1=1;x2=2|>") == []


def test_mask_paints_scaled_box_black(tmp_path):
    src = tmp_path / "src.png"
    Image.new("RGB", (200, 100), (255, 255, 255)).save(src)
    dst = tmp_path / "dst.png"
    mask_image(src, [{"x1": 10, "y1": 20, "x2": 110, "y2": 120, "w": 200, "h": 100}], dst)
    with Image.open(dst) as img:
        assert img.getpixel((60, 50)) == (0, 0, 0)
        assert img.getpixel((5, 5)) == (255, 255, 255)
    with Image.open(src) as img:
        assert img.getpixel((60, 50)) == (255, 255, 255)


def test_s2_seal_masked_from_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    dst = tmp_path / "s2_masked.png"
    result = mask_sample_image(
        "S2_seoul_worker_bronchitis", "clean", "receipt", "red circular seal", dst
    )
    assert len(result["boxes"]) >= 1
    with Image.open(dst) as img:
        px = img.load()
        assert any(px[x, y] == (0, 0, 0) for x in range(0, img.width, 7) for y in range(0, img.height, 7))


def test_s3_signature_masked_from_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAIMLENS_PROVIDER", "replay")
    dst = tmp_path / "s3_masked.png"
    result = mask_sample_image(
        "S3_us_tourist_hip_fracture", "clean", "medical_certificate", "signature", dst
    )
    assert len(result["boxes"]) >= 1
    with Image.open(dst) as img:
        px = img.load()
        assert any(px[x, y] == (0, 0, 0) for x in range(0, img.width, 7) for y in range(0, img.height, 7))
