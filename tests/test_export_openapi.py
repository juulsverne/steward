"""The exporter must produce the same document the running app serves, without secrets from .env."""

import json
import subprocess
import sys
from pathlib import Path


def test_export_writes_openapi_with_board_and_persona_routes(tmp_path):
    out = tmp_path / "openapi.json"
    result = subprocess.run([sys.executable, "scripts/export_openapi.py", "--out", str(out)],
                            capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 0, result.stderr
    document = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/board" in document["paths"]
    assert "/api/demo/persona" in document["paths"]
    schemas = document["components"]["schemas"]
    assert "BoardView" in schemas and "IssueDetailView" in schemas and "ExceptionDetail" in schemas
