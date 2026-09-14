"""API-only sandbox CLI. Durable invocation execution is supplied by B12."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import httpx
from rich.console import Console

from .config import settings
from .tools.client import TrustedTransport, _same_origin
from .tools.session import build_steward_tool_session

console = Console()


async def read_case(origin, token, invocation_id, *, transport=None):
    async with build_steward_tool_session(TrustedTransport(origin, token, invocation_id),
                                          http_transport=transport) as session:
        return await session.client.host_request("context")


async def resume_case(origin, token, invocation_id, *, transport=None):
    async with build_steward_tool_session(TrustedTransport(origin, token, invocation_id),
                                          http_transport=transport) as session:
        return await session.client.host_request("resume")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    configured_origin = os.getenv("STEWARD_ORIGIN", "http://127.0.0.1:8000")
    parser.add_argument("--origin", default=configured_origin)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("context", "resume"):
        commands.add_parser(name).add_argument("invocation_id")
    submit = commands.add_parser("submit", help="Submit a real sandbox resident event through FastAPI")
    submit.add_argument("--description", required=True)
    submit.add_argument("--location", required=True)
    submit.add_argument("--persona", default="resident-1")
    submit.add_argument("--observed-at")
    submit.add_argument("--image", type=Path)
    submit.add_argument("--key", default=None, help="Reuse this exact key to recover a lost submit response")
    args = parser.parse_args(argv)
    console.print(f"text model: {settings.resolved_text_model_id}  region: {settings.region}", markup=False)
    try:
        # Reuse the accepted origin validator even for the separate human bootstrap.
        TrustedTransport(args.origin, "validation-only", "cli-origin-validation")
        if args.command in {"context", "resume"}:
            TrustedTransport(configured_origin, "validation-only", "cli-origin-validation")
            if not _same_origin(httpx.URL(args.origin), httpx.URL(configured_origin)):
                console.print("Service reads require the configured STEWARD_ORIGIN; origin override refused.", markup=False)
                return 2
            token = os.getenv("STEWARD_SERVICE_TOKEN", "")
            if not token:
                console.print("STEWARD_SERVICE_TOKEN is required privately for service context reads.", markup=False)
                return 2
            action = read_case if args.command == "context" else resume_case
            result = asyncio.run(action(args.origin, token, args.invocation_id))
            console.print(json.dumps(result, indent=2), markup=False)
            if result["outcome"] != "OK":
                return 1
            if args.command == "resume":
                return 0 if result.get("reason_code") == "PROCESSING_ENABLED" else 2
            return 0
        key = args.key or "cli-signal-" + uuid4().hex
        headers = {"Origin": args.origin, "X-Steward-Request": "1", "Idempotency-Key": "persona-" + uuid4().hex}
        with httpx.Client(base_url=args.origin, trust_env=False, follow_redirects=False, timeout=20) as client:
            selected = client.post("/api/demo/persona", headers=headers, json={"persona_id": args.persona})
            if selected.status_code != 200:
                console.print("Sandbox persona selection failed.", markup=False)
                return 1
            files = {"description": (None, args.description), "location": (None, args.location)}
            if args.observed_at:
                files["observed_at"] = (None, args.observed_at)
            if args.image:
                if args.image.stat().st_size > 10 * 1024 * 1024:
                    raise ValueError("image exceeds upload bound")
                files["image"] = (args.image.name, args.image.read_bytes(), "application/octet-stream")
            console.print(f"Submission idempotency key: {key}", markup=False)
            response = client.post("/api/signals", headers={**headers, "Idempotency-Key": key}, files=files)
            # API error envelopes contain bounded public diagnostics, never SDK errors.
            payload = response.json()
            console.print(json.dumps(payload, indent=2), markup=False)
            return 0 if response.status_code == 202 else 1
    except (ValueError, OSError, httpx.HTTPError):
        console.print("API request failed. Preserve the submission key when its outcome is unknown.", markup=False)
        return 1


if __name__ == "__main__":
    sys.exit(main())
