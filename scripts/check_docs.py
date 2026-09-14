"""Check relative Markdown links and heading anchors across every tracked .md file.

Run from the repository root: uv run --no-sync python scripts/check_docs.py
Links inside fenced code blocks are ignored; external (scheme://, mailto:) links are skipped.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

FENCE = re.compile(r"```.*?```", re.DOTALL)
LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^#{1,6} (.+)$", re.MULTILINE)


def slugs(path: Path) -> set[str]:
    body = FENCE.sub("", path.read_text(encoding="utf-8"))
    return {re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in HEADING.findall(body)}


def tracked_markdown() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files", "*.md"], text=True)
    return [Path(line) for line in out.splitlines() if line]


def main() -> int:
    problems: list[str] = []
    checked = 0
    for path in tracked_markdown():
        body = FENCE.sub("", path.read_text(encoding="utf-8"))
        for destination in LINK.findall(body):
            if "://" in destination or destination.startswith("mailto:"):
                continue
            raw, _, anchor = unquote(destination).partition("#")
            target = path.parent / raw if raw else path
            if not target.exists():
                problems.append(f"{path}: missing target {destination}")
                continue
            if anchor and target.suffix == ".md" and anchor not in slugs(target):
                problems.append(f"{path}: missing anchor {destination}")
                continue
            checked += 1
    for line in problems:
        print(line)
    status = "FAIL" if problems else "PASS"
    print(f"{status}: {checked} relative links resolved, {len(problems)} broken")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
