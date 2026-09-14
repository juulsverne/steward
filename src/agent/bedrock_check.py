"""Bounded live Strands tool round trip; offline tests never need AWS credentials."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

PROMPT = "Call current_time once for UTC, then reply with only the timestamp it returns."


def tools_used(messages: list[dict]) -> list[str]:
    return [block["toolUse"]["name"] for message in messages if message["role"] == "assistant"
            for block in message.get("content", []) if "toolUse" in block]


def round_trip_passed(messages: list[dict], *, stop_reason: str) -> bool:
    if not messages or stop_reason != "end_turn" or messages[-1]["role"] != "assistant":
        return False
    final = " ".join(block.get("text", "") for block in messages[-1].get("content", []))
    pending = set()
    successful = False
    for message in messages:
        for block in message.get("content", []):
            use = block.get("toolUse", {})
            if message["role"] == "assistant" and use.get("name") == "current_time":
                pending.add(use["toolUseId"])
            result = block.get("toolResult", {})
            if (message["role"] == "user" and result.get("toolUseId") in pending
                    and result.get("status") == "success" and result.get("content")):
                successful = True
    return successful and bool(final.strip())


def build_check_agent():
    from botocore.config import Config
    from strands import Agent
    from strands.hooks import BeforeModelCallEvent, HookProvider
    from strands.models import BedrockModel
    from strands_tools import current_time

    from .aws_session import region_session
    from .config import settings

    class TwoCycles(HookProvider):
        def __init__(self):
            self.calls = 0

        def register_hooks(self, registry, **_):
            registry.add_callback(BeforeModelCallEvent, self.limit)

        def limit(self, event):
            self.calls += 1
            if self.calls > 2:
                event.cancel = "Bedrock preflight reached its two-model-call limit."

    return Agent(
        model=BedrockModel(
            model_id=settings.resolved_text_model_id, temperature=0, max_tokens=256,
            boto_session=region_session(settings.aws_profile, settings.region),
            boto_client_config=Config(connect_timeout=10, read_timeout=60,
                                      retries={"mode": "standard", "total_max_attempts": 2}),
        ),
        tools=[current_time], hooks=[TwoCycles()], retry_strategy=None, callback_handler=None,
    )


def run_check(*, agent_factory=None) -> dict:
    from .config import settings

    summary = {
        "checked_at": datetime.now(UTC).isoformat(), "mode": "live",
        "model_id": settings.resolved_text_model_id,
        "text_model_id": settings.resolved_text_model_id,
        "region": settings.region, "prompt": PROMPT,
        "passed": False, "tools_called": [], "messages": [],
    }
    started = time.perf_counter()
    agent = None
    try:
        agent = (agent_factory or build_check_agent)()
        result = agent(PROMPT)
        summary.update(stop_reason=result.stop_reason, reply=str(result).strip()[:200])
        summary["passed"] = round_trip_passed(agent.messages, stop_reason=result.stop_reason)
        metrics = agent.event_loop_metrics.get_summary()
        summary["usage"] = metrics["accumulated_usage"]
        summary["cycles"] = metrics["total_cycles"]
    except Exception as exc:  # noqa: BLE001 - CLI boundary retains failed-run evidence
        # Preserve a safe failure type, not credential-bearing diagnostics or private reasoning.
        summary["passed"] = False
        summary["error"] = type(exc).__name__
    if agent is not None:
        summary["tools_called"] = tools_used(agent.messages)
        summary["messages"] = [{
            "role": message["role"], "content": [
                {key: block[key]} for block in message.get("content", [])
                for key in ("text", "toolUse", "toolResult") if key in block
            ],
        } for message in agent.messages]
    summary["latency_s"] = round(time.perf_counter() - started, 3)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    out = args.out or Path(".steward") / f"bedrock-check-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as file:
        summary = run_check()
        json.dump(summary, file, indent=2)
        file.write("\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "messages"}, indent=2))
    print(f"Recorded: {out.resolve()}")
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
