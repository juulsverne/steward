import json

import pytest
from PIL import Image, ImageDraw

from agent.images import (
    REUSE_MAX_DISTANCE,
    build_manifest,
    dhash,
    hamming,
    looks_reused,
    normalize,
    sha256_of,
)


def scene(path, *, couch=True, bags=True, flipped=False):
    """Draw a deterministic 'sidewalk' scene: gray ground, a couch rectangle, bag circles."""
    image = Image.new("RGB", (640, 480), (200, 200, 200))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 300, 640, 480], fill=(120, 120, 120))
    if couch:
        draw.rectangle([180, 220, 460, 330], fill=(90, 50, 40))
    if bags:
        for x in (500, 540, 580):
            draw.ellipse([x, 300, x + 30, 330], fill=(20, 20, 20))
    if flipped:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    image.save(path)
    return path


def test_normalize_strips_metadata_and_bounds_size(tmp_path):
    src = scene(tmp_path / "raw.png")
    out = normalize(src, tmp_path / "before.jpg", max_side=320)
    with Image.open(out) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        assert max(img.size) == 320
        assert "exif" not in img.info


def test_reencoded_copy_is_detected_by_dhash_even_though_sha_differs(tmp_path):
    original = normalize(scene(tmp_path / "raw.png"), tmp_path / "after.jpg")
    copy = normalize(original, tmp_path / "reused.jpg", quality=50)
    assert sha256_of(original) != sha256_of(copy)
    assert hamming(dhash(original), dhash(copy)) <= REUSE_MAX_DISTANCE
    assert looks_reused(dhash(copy), [dhash(original)])


def test_reuse_is_judged_against_prior_completion_photos_not_the_before_photo(tmp_path):
    before = normalize(scene(tmp_path / "b.png"), tmp_path / "before.jpg")
    cleared = normalize(scene(tmp_path / "c.png", couch=False, bags=False), tmp_path / "after.jpg")
    unrelated = normalize(scene(tmp_path / "u.png", flipped=True), tmp_path / "unrelated.jpg")
    # A legitimate completion photo is never reuse when no prior completion photo exists,
    # however close it sits to the before photo (same scene is the vision model's question).
    assert not looks_reused(dhash(cleared), [])
    # Sanity check on the hash itself: different scenes hash differently.
    assert hamming(dhash(before), dhash(unrelated)) > REUSE_MAX_DISTANCE
    assert not looks_reused(dhash(unrelated), [dhash(cleared)])


def test_hash_helpers_are_well_formed():
    assert hamming("0000000000000000", "ffffffffffffffff") == 64
    assert hamming("00000000000000ff", "0000000000000000") == 8
    with pytest.raises(ValueError):
        hamming("zz", "00")


def test_manifest_requires_all_five_roles_and_records_fingerprints(tmp_path):
    normalize(scene(tmp_path / "b.png"), tmp_path / "before.jpg")
    normalize(scene(tmp_path / "m.png", couch=False), tmp_path / "middle.jpg")
    after = normalize(scene(tmp_path / "a.png", couch=False, bags=False), tmp_path / "after.jpg")
    normalize(scene(tmp_path / "u.png", flipped=True), tmp_path / "unrelated.jpg")
    with pytest.raises(ValueError, match="reused.jpg"):
        build_manifest(tmp_path)
    normalize(after, tmp_path / "reused.jpg", quality=50)
    manifest = build_manifest(tmp_path)
    assert manifest["provenance"] == "synthetic"
    assert set(manifest["images"]) == {"before", "middle", "after", "unrelated", "reused"}
    assert manifest["images"]["before"]["sha256"] == sha256_of(tmp_path / "before.jpg")
    assert len(manifest["images"]["before"]["dhash"]) == 16
    assert manifest["images"]["reused"]["reuse_of"] == "after"
    assert manifest["images"]["reused"]["dhash_distance_to_after"] <= REUSE_MAX_DISTANCE
    assert isinstance(manifest["info_dhash_distance_before_to_after"], int)
    written = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert written == manifest
