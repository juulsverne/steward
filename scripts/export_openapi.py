"""Dump the FastAPI OpenAPI document without a running server or real secrets.

Usage: uv run --no-sync python scripts/export_openapi.py [--out frontend/openapi.json]
The throwaway secrets below satisfy _validate_setup only; nothing is started or written elsewhere.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EXPORT_SIGNING = "4f1c8a2e9b7d3056c1e8f2a4b6d9037e5a1c3f7b9d2e4068a7c5e3b1d9f7a2c4"
EXPORT_TOKEN = "9e3b7d1f5a2c8046e7b3d9f1a5c2e8b4d6f0a7c3e9b5d1f7a3c8e2b6d4f0a9c1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "frontend" / "openapi.json")
    args = parser.parse_args()
    from agent.api import create_app
    from agent.config import ApiSettings

    with tempfile.TemporaryDirectory() as tmp:
        settings = ApiSettings(store_path=Path(tmp) / "export.sqlite3", origin="http://localhost:8000",
                               local_http=True, session_secret=EXPORT_SIGNING, service_token=EXPORT_TOKEN,
                               policy_path=ROOT / "data" / "policy.yaml", fixture_root=ROOT / "data",
                               frontend_dist=None)
        document = create_app(settings).openapi()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out} with {len(document['paths'])} paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
