"""Image fingerprints and normalization for demo proof. dHash detects reuse, not scene identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image

REUSE_MAX_DISTANCE = 6
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_PIXELS = 20_000_000


class UploadError(ValueError):
    def __init__(self, message: str, *, status: int = 415):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class NormalizedImage:
    bytes: bytes
    image_sha256: str
    image_dhash: str
    content_type: str = "image/jpeg"

    @property
    def size_bytes(self) -> int:
        return len(self.bytes)


@dataclass(frozen=True)
class StoredImage:
    image_ref: str
    image_sha256: str
    size_bytes: int


def _dhash_image(img: Image.Image, size: int = 8) -> str:
    gray = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = _pixel_data(gray)
    bits = 0
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:0{size * size // 4}x}"


def decode_upload(raw: bytes, declared_content_type: str | None) -> NormalizedImage:
    """Validate bytes before normalization; browser filenames and MIME claims are never storage input."""
    if not isinstance(raw, bytes) or not raw:
        raise UploadError("image body is required")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise UploadError("image exceeds 10 MiB", status=413)
    if declared_content_type not in {"image/jpeg", "image/png"}:
        raise UploadError("image content type must be JPEG or PNG")
    try:
        with Image.open(BytesIO(raw)) as verified:
            verified.verify()
        with Image.open(BytesIO(raw)) as image:
            if image.format not in {"JPEG", "PNG"} or getattr(image, "n_frames", 1) != 1:
                raise UploadError("image must be a single JPEG or PNG")
            actual_content_type = "image/jpeg" if image.format == "JPEG" else "image/png"
            if declared_content_type != actual_content_type:
                raise UploadError("image content type does not match image bytes")
            if image.width * image.height > MAX_UPLOAD_PIXELS:
                raise UploadError("image dimensions exceed the upload limit", status=413)
            image.load()
            rgb = image.convert("RGB")
            rgb.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            clean = Image.new("RGB", rgb.size)
            clean.putdata(_pixel_data(rgb))
            output = BytesIO()
            clean.save(output, format="JPEG", quality=85, optimize=True)
            normalized = output.getvalue()
            # Fingerprint the exact normalized JPEG that storage persists. JPEG
            # encoding can alter pixels slightly from the clean in-memory image.
            with Image.open(BytesIO(normalized)) as stored:
                fingerprint = _dhash_image(stored)
    except UploadError:
        raise
    except Exception as exc:  # Pillow error types vary by release
        raise UploadError("malformed image") from exc
    return NormalizedImage(normalized, hashlib.sha256(normalized).hexdigest(), fingerprint)


class ImageStorage:
    """Private local storage keyed exclusively by an opaque server-generated reference."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, image_ref: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", image_ref):
            raise UploadError("invalid image reference")
        path = (self.root / f"{image_ref}.jpg").resolve()
        if path.parent != self.root:
            raise UploadError("invalid image reference")
        return path

    def put(self, image_ref: str, image: NormalizedImage) -> StoredImage:
        path = self._path(image_ref)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / f".{image_ref}.{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as output:
                output.write(image.bytes)
                output.flush()
                os.fsync(output.fileno())
            try:
                # A hard-link publication is exclusive: unlike replace(), it can never overwrite
                # an immutable reference that another request has already committed.
                os.link(temporary, path)
            except FileExistsError:
                pass
            current = path.read_bytes()
        except OSError as exc:
            raise UploadError("image publication failed", status=409) from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        if current != image.bytes:
            raise UploadError("storage reference conflict", status=409)
        if hashlib.sha256(current).hexdigest() != image.image_sha256:
            raise UploadError("stored image integrity failure")
        return StoredImage(image_ref, image.image_sha256, len(current))

    def open(self, image_ref: str) -> bytes:
        path = self._path(image_ref)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise KeyError(image_ref) from exc


def known_synthetic_fixture(raw: bytes, normalized: NormalizedImage,
                            manifest_path: str | Path = Path("data/images/manifest.json")) -> bool:
    """Recognize exact reviewed bytes in the original and fixed supplemental catalogs.

    The server selects catalogs; upload fields never select them or assert provenance.
    Each entry must still match its published file before even its source hash is trusted.
    """
    primary = Path(manifest_path)
    raw_hash = hashlib.sha256(raw).hexdigest()
    return any(_matches_synthetic_catalog(catalog, raw_hash, normalized.image_sha256)
               for catalog in (primary, primary.parent / "supplemental" / "manifest.json"))


def _matches_synthetic_catalog(manifest_path: Path, raw_hash: str, normalized_hash: str) -> bool:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(manifest, dict) or manifest.get("provenance") != "synthetic":
        return False
    entries = manifest.get("images")
    if not isinstance(entries, dict):
        return False
    root = manifest_path.parent.resolve()
    for entry in entries.values():
        if not isinstance(entry, dict) or entry.get("provenance", "synthetic") != "synthetic":
            continue
        expected_hash = entry.get("sha256")
        filename = entry.get("file")
        if (not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
                or not isinstance(filename, str) or Path(filename).name != filename):
            continue
        try:
            candidate = (root / filename).resolve()
            if candidate.parent != root or not candidate.is_file():
                continue
            candidate_bytes = candidate.read_bytes()
            if hashlib.sha256(candidate_bytes).hexdigest() != expected_hash:
                continue
            if raw_hash in (expected_hash, entry.get("source_sha256")):
                return True
            candidate_type = "image/png" if candidate.suffix.lower() == ".png" else "image/jpeg"
            candidate_normal = decode_upload(candidate_bytes, candidate_type)
            if (raw_hash == candidate_normal.image_sha256
                    or candidate_normal.image_sha256 == normalized_hash):
                return True
        except (OSError, ValueError):
            continue
    return False


IMAGE_ROLES = {
    "before": "couch and dumped bags on the sidewalk at the work area",
    "middle": "couch removed; dumped bags and debris remain in the work area",
    "after": "couch and bags removed; work area clear",
    "unrelated": "a different sidewalk scene; must fail same_scene",
    "reused": "re-encoded copy of after.jpg; must be caught by dhash despite a new sha256",
}


def sha256_of(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pixel_data(img: Image.Image) -> list:
    """Flattened pixel values, without tripping Pillow's ``getdata`` deprecation warning."""
    get_flattened = getattr(img, "get_flattened_data", None)
    return list(get_flattened()) if get_flattened is not None else list(img.getdata())


def dhash(path: str | Path, size: int = 8) -> str:
    """Difference hash: compare horizontally adjacent pixels of a small grayscale thumbnail."""
    with Image.open(path) as img:
        gray = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
        pixels = _pixel_data(gray)
    bits = 0
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    try:
        return (int(a, 16) ^ int(b, 16)).bit_count()
    except ValueError as exc:
        raise ValueError("hashes must be hexadecimal strings") from exc


def looks_reused(candidate_hash: str, prior_hashes: list[str]) -> bool:
    """Is this completion photo a recycled prior completion photo?

    ``prior_hashes`` are hashes of previously submitted completion photos (this job and
    other jobs). Never include the before photo: a legitimate after photo of the same
    scene is expected to be perceptually close to it. Scene identity is the vision
    model's ``same_scene`` question, not a hash question.
    """
    return any(hamming(candidate_hash, prior) <= REUSE_MAX_DISTANCE for prior in prior_hashes)


def normalize(src: str | Path, dst: str | Path, *, max_side: int = 1024, quality: int = 85) -> Path:
    """Write an RGB JPEG with no metadata and the longest side at most ``max_side``."""
    dst = Path(dst)
    with Image.open(src) as img:
        rgb = img.convert("RGB")
        rgb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        clean = Image.new("RGB", rgb.size)
        clean.putdata(_pixel_data(rgb))
        clean.save(dst, format="JPEG", quality=quality, optimize=True)
    return dst


def build_manifest(directory: str | Path) -> dict:
    directory = Path(directory)
    images: dict[str, dict] = {}
    for role, condition in IMAGE_ROLES.items():
        path = directory / f"{role}.jpg"
        if not path.is_file():
            raise ValueError(f"missing {role}.jpg in {directory}")
        images[role] = {
            "file": path.name, "intended_condition": condition,
            "sha256": sha256_of(path), "dhash": dhash(path), "bytes": path.stat().st_size,
        }
    images["reused"]["reuse_of"] = "after"
    images["reused"]["dhash_distance_to_after"] = hamming(
        images["reused"]["dhash"], images["after"]["dhash"]
    )
    manifest = {
        "provenance": "synthetic",
        "label": "Generated demo images; not photographs of a real condition",
        "reuse_max_distance": REUSE_MAX_DISTANCE,
        "info_dhash_distance_before_to_after": hamming(
            images["before"]["dhash"], images["after"]["dhash"]
        ),
        "images": images,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    norm = sub.add_parser("normalize", help="write a clean RGB JPEG")
    norm.add_argument("src", type=Path)
    norm.add_argument("dst", type=Path)
    norm.add_argument("--quality", type=int, default=85)
    norm.add_argument("--max-side", type=int, default=1024)
    man = sub.add_parser("manifest", help="fingerprint the five demo images")
    man.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "normalize":
        out = normalize(args.src, args.dst, max_side=args.max_side, quality=args.quality)
        print(json.dumps({"file": str(out), "sha256": sha256_of(out), "dhash": dhash(out)}))
    else:
        print(json.dumps(build_manifest(args.directory), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
