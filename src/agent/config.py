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
    text_model_id: str | None = None
    vision_model_id: str | None = None

    @staticmethod
    def _configured_model(value: str | None) -> str | None:
        """Return a nonblank model value, keeping blank environment settings as fallbacks."""
        if value and value.strip():
            return value.strip()
        return None

    @property
    def resolved_text_model_id(self) -> str:
        return self._configured_model(self.text_model_id) or self._configured_model(self.model_id) or DEFAULT_MODEL_ID

    @property
    def resolved_vision_model_id(self) -> str:
        return self._configured_model(self.vision_model_id) or self._configured_model(self.model_id) or DEFAULT_MODEL_ID

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            model_id=cls._configured_model(os.getenv("BEDROCK_MODEL_ID")) or DEFAULT_MODEL_ID,
            region=os.getenv("AWS_REGION", "us-west-2"),
            temperature=float(os.getenv("AGENT_TEMPERATURE", "0.3")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            text_model_id=cls._configured_model(os.getenv("BEDROCK_TEXT_MODEL_ID")),
            vision_model_id=cls._configured_model(os.getenv("BEDROCK_VISION_MODEL_ID")),
        )


settings = Settings.from_env()
