"""Runtime configuration, loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Strands' current default. Override with BEDROCK_MODEL_ID in .env.
DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-6"


@dataclass(frozen=True)
class Settings:
    model_id: str
    region: str
    temperature: float
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            model_id=os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
            region=os.getenv("AWS_REGION", "us-west-2"),
            temperature=float(os.getenv("AGENT_TEMPERATURE", "0.3")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


settings = Settings.from_env()
