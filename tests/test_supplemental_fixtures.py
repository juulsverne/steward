"""Trusted fixture recognition is exact provenance, never a visual classifier."""
import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from agent.images import decode_upload, dhash, known_synthetic_fixture

CATALOG = Path("data/images/supplemental/manifest.json")
NAMES = (
    "persistence-later", "ambiguous-before", "mixed-hazard",
    "holdout-before", "holdout-partial", "holdout-complete",
)


def image_bytes(color="red"):
    output = BytesIO()
    Image.new("RGB", (32, 24), color).save(output, format="PNG")
    return output.getvalue()


def write_catalog(tmp_path):
    raw = image_bytes()
    normalized = decode_upload(raw, "image/png")
    published = tmp_path / "fixture.jpg"
    published.write_bytes(normalized.bytes)
    document = {"provenance": "synthetic", "images": {"fixture": {
        "file": published.name, "sha256": normalized.image_sha256,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }}}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    return raw, normalized, document, manifest


@pytest.mark.parametrize("name", NAMES)
def test_published_and_normalized_reuploads_keep_exact_synthetic_provenance(name):
    manifest = json.loads(CATALOG.read_text(encoding="utf-8"))
    entry = manifest["images"][name]
    path = CATALOG.parent / entry["file"]
    raw = path.read_bytes()
    normalized = decode_upload(raw, "image/jpeg")
    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    assert len(raw) == entry["bytes"] and dhash(path) == entry["dhash"]
    with Image.open(path) as image:
        assert list(image.size) == entry["dimensions"]
        assert image.mode == "RGB" and "exif" not in image.info
    assert known_synthetic_fixture(raw, normalized)
    assert known_synthetic_fixture(normalized.bytes, decode_upload(normalized.bytes, "image/jpeg"))


def test_original_generated_source_hash_is_recognized(tmp_path):
    raw, normalized, _, manifest = write_catalog(tmp_path)
    assert hashlib.sha256(raw).hexdigest() != normalized.image_sha256
    assert known_synthetic_fixture(raw, normalized, manifest)
    unrelated = image_bytes("blue")
    assert not known_synthetic_fixture(unrelated, decode_upload(unrelated, "image/png"), manifest)


@pytest.mark.parametrize("failure", [
    "list_document", "list_images", "bad_json", "not_synthetic", "entry_not_synthetic",
    "bad_entry", "bad_hash", "missing_file", "traversal", "absolute_path", "wrong_bytes",
])
def test_untrusted_or_incomplete_catalog_entries_fail_closed(tmp_path, failure):
    raw, normalized, document, manifest = write_catalog(tmp_path)
    entry = document["images"]["fixture"]
    if failure == "list_document":
        document = []
    elif failure == "list_images":
        document["images"] = []
    elif failure == "not_synthetic":
        document["provenance"] = "live"
    elif failure == "entry_not_synthetic":
        entry["provenance"] = "live"
    elif failure == "bad_entry":
        document["images"]["fixture"] = "invalid"
    elif failure == "bad_hash":
        entry["sha256"] = "invalid"
    elif failure == "missing_file":
        (tmp_path / "fixture.jpg").unlink()
    elif failure == "traversal":
        entry["file"] = "../fixture.jpg"
    elif failure == "absolute_path":
        entry["file"] = str((tmp_path / "fixture.jpg").resolve())
    elif failure == "wrong_bytes":
        # Matching source hash cannot bypass integrity of its reviewed published asset.
        (tmp_path / "fixture.jpg").write_bytes(decode_upload(image_bytes("blue"), "image/png").bytes)
    manifest.write_text("{" if failure == "bad_json" else json.dumps(document), encoding="utf-8")
    assert not known_synthetic_fixture(raw, normalized, manifest)


@pytest.mark.parametrize("document", [None, "{", "[]", '{"provenance":"live","images":{}}'])
def test_bad_supplemental_catalog_does_not_break_original_catalog(tmp_path, document):
    raw, normalized, _, manifest = write_catalog(tmp_path)
    supplemental = tmp_path / "supplemental"
    supplemental.mkdir()
    if document is not None:
        (supplemental / "manifest.json").write_text(document, encoding="utf-8")
    assert known_synthetic_fixture(raw, normalized, manifest)


def test_bad_primary_does_not_hide_valid_fixed_supplemental_catalog(tmp_path):
    primary = tmp_path / "manifest.json"
    primary.write_text("[]", encoding="utf-8")
    supplemental = tmp_path / "supplemental"
    supplemental.mkdir()
    raw, normalized, _, _ = write_catalog(supplemental)
    assert known_synthetic_fixture(raw, normalized, primary)


def test_original_catalog_assets_still_match_frozen_manifest():
    manifest_path = Path("data/images/manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["images"]) == 5
    for entry in manifest["images"].values():
        raw = (manifest_path.parent / entry["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        assert known_synthetic_fixture(raw, decode_upload(raw, "image/jpeg"))
