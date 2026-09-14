from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from agent.config import DEFAULT_MODEL_ID, Settings


def make_settings(**changes) -> Settings:
    return Settings(
        model_id=DEFAULT_MODEL_ID,
        region="us-west-2",
        temperature=0.3,
        log_level="INFO",
        **changes,
    )


@pytest.mark.parametrize("temperature", [float("nan"), float("inf"), float("-inf"), -.01, 1.01,
                                       True, False, None, "0.3"])
def test_invalid_temperature_rejected_before_provider_construction(monkeypatch, temperature):
    from agent import core
    calls = []
    monkeypatch.setattr(core, "settings", replace(make_settings(), temperature=temperature))
    monkeypatch.setattr(core, "BedrockModel", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ValueError):
        core.build_model()
    assert calls == []


@pytest.mark.parametrize("temperature", [0, .3, 1.0])
def test_normal_temperature_keeps_resolved_role_and_provider_bounds(monkeypatch, temperature):
    from agent import core
    calls = []
    monkeypatch.setattr(core, "settings", replace(make_settings(text_model_id="text-override"), temperature=temperature))
    monkeypatch.setattr(core, "BedrockModel", lambda **kwargs: calls.append(kwargs))
    core.build_model()
    assert calls[0]["temperature"] == temperature
    assert calls[0]["model_id"] == "text-override"
    assert calls[0]["boto_client_config"].retries == {"total_max_attempts": 1}


def test_role_environment_settings_fall_back_independently(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "legacy-model")
    monkeypatch.setenv("BEDROCK_TEXT_MODEL_ID", "text-model")
    monkeypatch.setenv("BEDROCK_VISION_MODEL_ID", "")

    configured = Settings.from_env()

    assert configured.model_id == "legacy-model"
    assert configured.resolved_text_model_id == "text-model"
    assert configured.resolved_vision_model_id == "legacy-model"


def test_legacy_constructor_and_blank_values_keep_sonnet_default(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.setenv("BEDROCK_TEXT_MODEL_ID", "  ")
    monkeypatch.setenv("BEDROCK_VISION_MODEL_ID", "")

    configured = Settings.from_env()
    constructed = Settings(DEFAULT_MODEL_ID, "us-west-2", 0.3, "INFO")

    assert configured.resolved_text_model_id == DEFAULT_MODEL_ID
    assert configured.resolved_vision_model_id == DEFAULT_MODEL_ID
    assert constructed.resolved_text_model_id == DEFAULT_MODEL_ID
    assert constructed.resolved_vision_model_id == DEFAULT_MODEL_ID


def test_agent_build_uses_only_the_resolved_text_model(monkeypatch):
    from agent import core

    captured = {}

    class FakeBedrockModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(core, "BedrockModel", FakeBedrockModel)
    monkeypatch.setattr(core, "settings", make_settings(
        text_model_id="text-model", vision_model_id="vision-model",
    ))

    core.build_model()

    assert captured["model_id"] == "text-model"


def test_terminal_banner_reports_the_resolved_text_model_role(monkeypatch):
    from agent import cli

    printed = []

    class Console:
        def print(self, *args, **kwargs):
            printed.append((args, kwargs))

        def input(self, _prompt):
            return "exit"

    monkeypatch.setattr(cli, "console", Console())
    monkeypatch.setattr(cli, "settings", make_settings(
        text_model_id="text-model", vision_model_id="vision-model",
    ))
    monkeypatch.delenv("STEWARD_SERVICE_TOKEN", raising=False)
    assert cli.main(["context", "saved-invocation"]) == 2
    assert "text model: text-model" in printed[0][0][0]


def test_preflight_artifact_records_the_resolved_text_model(monkeypatch):
    from agent import bedrock_check, config

    class Agent:
        def __init__(self):
            self.messages = [
                {"role": "assistant", "content": [{"toolUse": {
                    "name": "current_time", "toolUseId": "clock-1", "input": {},
                }}]},
                {"role": "user", "content": [{"toolResult": {
                    "toolUseId": "clock-1", "status": "success", "content": [{"text": "time"}],
                }}]},
                {"role": "assistant", "content": [{"text": "time"}]},
            ]
            self.event_loop_metrics = SimpleNamespace(
                get_summary=lambda: {"accumulated_usage": {}, "total_cycles": 2},
            )

        def __call__(self, _prompt):
            return SimpleNamespace(stop_reason="end_turn")

    monkeypatch.setattr(config, "settings", make_settings(
        text_model_id="text-model", vision_model_id="vision-model",
    ))

    result = bedrock_check.run_check(agent_factory=Agent)

    assert result["text_model_id"] == "text-model"


def jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (24, 24), "gray").save(output, format="JPEG")
    return output.getvalue()


def test_inspection_client_and_spike_artifact_use_only_the_resolved_vision_model(monkeypatch):
    from agent import vision, vision_spike

    configured = make_settings(text_model_id="text-model", vision_model_id="vision-model")
    monkeypatch.setattr(vision, "settings", configured)
    monkeypatch.setattr(vision_spike, "settings", configured)

    class Client:
        request = None

        def converse(self, **request):
            self.request = request
            return {
                "stopReason": "tool_use",
                "output": {"message": {"role": "assistant", "content": [{"toolUse": {
                    "name": "report_findings", "input": {
                        "target_present_before": True, "same_scene": True,
                        "target_removed": True, "no_new_hazard": True,
                        "area_clear": True, "observations": ["Clear sidewalk."],
                    },
                }}]}},
            }

    client = Client()
    vision.inspect_pair_result(jpeg(), jpeg(), target="couch", work_area="sidewalk", client=client)
    result = vision_spike.run_spike(
        Path("data/images"), repeats=1, interval_s=0,
        inspector=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    assert client.request["modelId"] == "vision-model"
    assert result["vision_model_id"] == "vision-model"


def test_profile_model_session_resolves_credentials_in_the_profile_region(monkeypatch):
    """A Bedrock-region session cannot refresh an `aws login` token issued elsewhere."""
    from agent import aws_session, core

    calls = []
    captured = {}
    monkeypatch.setattr(aws_session, "region_session",
                        lambda profile, region: calls.append((profile, region)) or "model-session")
    monkeypatch.setattr(core, "BedrockModel", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(core, "settings", make_settings(aws_profile="pc"))
    core.build_model()
    assert calls == [("pc", "us-west-2")]
    assert captured["boto_session"] == "model-session"
    assert "region_name" not in captured
