"""Image fingerprints and normalization for demo proof. dHash detects reuse, not scene identity."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

REUSE_MAX_DISTANCE = 6
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
