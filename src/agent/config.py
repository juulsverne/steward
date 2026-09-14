"""Runtime configuration, loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

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
    aws_profile: str | None = None
    max_output_tokens: int = 2048
    provider_timeout_seconds: float = 30.0

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
            aws_profile=cls._configured_model(os.getenv("AWS_PROFILE")),
            max_output_tokens=int(os.getenv("AGENT_MAX_OUTPUT_TOKENS", "2048")),
            provider_timeout_seconds=float(os.getenv("AGENT_PROVIDER_TIMEOUT_SECONDS", "30")),
        )


settings = Settings.from_env()


if TYPE_CHECKING:
    from .actors import DemoPersona


@dataclass(frozen=True)
class ApiSettings:
    """Web-only setup, validated at app creation. Never generate or write secrets."""

    store_path: Path
    origin: str
    session_secret: str = field(repr=False)
    service_token: str = field(repr=False)
    image_root: Path = Path(".steward/images")
    local_http: bool = False
    district_id: str = "south_loop_demo"
    policy_path: Path = Path("data/policy.yaml")
    development_origins: tuple[str, ...] = ()
    personas: tuple[DemoPersona, ...] | None = None
    runtime_enabled: bool = False

    @classmethod
    def from_env(cls) -> ApiSettings:
        mode = os.getenv("STEWARD_LOCAL_HTTP", "false")
        if mode not in {"true", "false"}:
            raise ValueError("STEWARD_LOCAL_HTTP must be true or false")
        runtime = os.getenv("STEWARD_RUNTIME_ENABLED", "false")
        if runtime not in {"true", "false"}:
            raise ValueError("STEWARD_RUNTIME_ENABLED must be true or false")
        return cls(
            store_path=Path(os.getenv("STEWARD_STORE_PATH", ".steward/steward.sqlite3")),
            image_root=Path(os.getenv("STEWARD_IMAGE_ROOT", ".steward/images")),
            origin=os.getenv("STEWARD_ORIGIN", ""),
            session_secret=os.getenv("STEWARD_SESSION_SECRET", ""),
            service_token=os.getenv("STEWARD_SERVICE_TOKEN", ""),
            local_http=mode == "true",
            runtime_enabled=runtime == "true",
            development_origins=tuple(filter(None, (
                x.strip() for x in os.getenv("STEWARD_DEVELOPMENT_ORIGINS", "").split(",")
            ))),
        )
