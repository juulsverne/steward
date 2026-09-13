"""Agent construction.

This is the seam where your idea plugs in: edit SYSTEM_PROMPT to define what the
agent is for, and register the tools that let it actually *do* the work.

Judging note: "Does the code reflect genuine effort and a working, non-trivial
implementation?" -- tools that take real action score better than tools that chat.
"""

from __future__ import annotations

import logging

from strands import Agent
from strands.models import BedrockModel

from .config import settings
from .tools import TOOLS

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful agent that completes tasks end to end.

<!-- TODO: Replace this with your agent's real identity and operating rules. -->

Operating principles:
- Do the work; do not merely describe how the work could be done.
- Use your tools to take real action rather than guessing at results.
- When a decision genuinely needs a human, ask one clear question and stop.
- Be concise. Report what you did, what changed, and anything left outstanding.
"""


def build_model() -> BedrockModel:
    """Bedrock model provider, configured from the environment."""
    return BedrockModel(
        model_id=settings.resolved_text_model_id,
        region_name=settings.region,
        temperature=settings.temperature,
    )


def build_agent(*, callback_handler=..., system_prompt: str | None = None) -> Agent:
    """Create the agent.

    Args:
        callback_handler: Strands streaming callback. Leave as the default sentinel
            to keep Strands' built-in printing handler; pass ``None`` to silence it
            (which you want when you are streaming yourself, e.g. in a web server).
        system_prompt: Override the default prompt, mainly useful in tests.
    """
    kwargs = {
        "model": build_model(),
        "system_prompt": system_prompt or SYSTEM_PROMPT,
        "tools": TOOLS,
    }
    if callback_handler is not ...:
        kwargs["callback_handler"] = callback_handler

    logger.debug("Building agent with %d tools on text model %s", len(TOOLS),
                 settings.resolved_text_model_id)
    return Agent(**kwargs)
