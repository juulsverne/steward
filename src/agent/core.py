"""Fresh sequential Steward agent; the API remains the only state owner."""
from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Literal, Protocol
from uuid import uuid4

from botocore.config import Config
from strands import Agent
from strands.hooks import (
    AfterInvocationEvent,
    AfterModelCallEvent,
    AfterToolCallEvent,
    AfterToolsEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
)
from strands.models import BedrockModel
from strands.tools.executors import SequentialToolExecutor

from .case_contracts import CaseContext
from .config import settings
from .contracts import ModelUsage, Record, Text
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, case_prompt

logger = logging.getLogger(__name__)
from .tools.lifecycle import LifecycleUncertainty, UncertaintyKind
from .tools.protocol import OPERATIONS, SCHEMA_VERSION, Command, build_command
from .tools.session import InvocationToolSession


@dataclass(frozen=True)
class ExecutionRequest:
    """Awaited trusted runner authorization; not a model-controlled tool input."""
    kind: Literal["context", "model", "tool"]
    ordinal: int
    invocation_id: str
    call_ref: str | None = None
    command: Command | None = None
    case: CaseContext | None = None


@dataclass(frozen=True)
class ExecutionObservation:
    kind: Literal["context", "model", "tool", "invocation"]
    ordinal: int
    invocation_id: str
    outcome: str
    call_ref: str | None = None
    result_json: str | None = None
    usage: ModelUsage | None = None
    elapsed_ms: int | None = None


class ExecutionLifecycle(Protocol):
    async def authorize(self, request: ExecutionRequest) -> bool: ...
    async def observe(self, observation: ExecutionObservation) -> bool: ...


class InProcessExecutionLifecycle:
    """Explicitly non-durable. B12 supplies persisted permits and acknowledgments."""
    async def authorize(self, request):
        return True

    async def observe(self, observation):
        return True


@dataclass(frozen=True)
class ProviderObservation:
    invocation_id: str
    ordinal: int
    operation: Literal["Converse", "ConverseStream"]
    observed_at_monotonic: float
    kind: Literal["sdk_before_send"] = "sdk_before_send"


class ProviderObserver:
    """Nonthrowing SDK pre-send observations, never send/acceptance/billing receipts."""
    def __init__(self, model, invocation_id, callback: Callable[[ProviderObservation], None] | None):
        self.events = getattr(getattr(getattr(model, "client", None), "meta", None), "events", None)
        self.callback = callback
        self.invocation_id = invocation_id
        self.ordinal = 0
        self.identity = "steward-observer-" + uuid4().hex
        self.registered = []

    def start(self):
        if self.events is None:
            return
        for operation in ("Converse", "ConverseStream"):
            name = "before-send.bedrock-runtime." + operation
            def observe(*_args, _operation=operation, **_kwargs):
                self.ordinal += 1
                if self.callback:
                    try:
                        self.callback(ProviderObservation(self.invocation_id, self.ordinal,
                            _operation, monotonic()))
                    except Exception:  # noqa: BLE001, S110 - never log private observer exception material
                        pass  # observational only; never gates an already-started SDK call
            self.events.register_last(name, observe, unique_id=self.identity)
            self.registered.append(name)

    def close(self):
        for name in self.registered:
            self.events.unregister(name, unique_id=self.identity)
        self.registered.clear()


class InvocationHooks(HookProvider):
    """Awaitable control plane, distinct from best-effort SDK observations."""
    def __init__(self, client, *, deadline_at, lifecycle=None, provider=None):
        self.client = client
        self.invocation_id = client.transport.invocation_id
        self.deadline_at = deadline_at
        self.lifecycle = lifecycle or InProcessExecutionLifecycle()
        self.provider = provider
        self.model_cycles = 0
        self.tool_requests = 0
        self.host_reads = 0
        self.stopped = None
        self.interruption: UncertaintyKind | None = None
        self.case = None
        self.usage = None
        self._deadline_handle = None

    def register_hooks(self, registry):
        for event, method in ((BeforeModelCallEvent, self.before_model),
                (AfterModelCallEvent, self.after_model), (BeforeToolCallEvent, self.before_tool),
                (AfterToolCallEvent, self.after_tool), (AfterToolsEvent, self.after_tools),
                (AfterInvocationEvent, self.after_invocation)):
            registry.add_callback(event, method)

    async def _authorize(self, request):
        if self.stopped or monotonic() >= self.deadline_at:
            self.stopped = self.stopped or "DEADLINE_EXCEEDED"
            return False
        try:
            async with asyncio.timeout_at(self.deadline_at):
                allowed = await self.lifecycle.authorize(request)
            if allowed is not True:
                raise ValueError("authorization refused")
            return True
        except (LifecycleUncertainty, TimeoutError):
            self.interruption = "COORDINATOR_CONTROL_UNCERTAIN"
            self.stopped = "EXECUTION_AUTHORIZATION_FAILED"
            return False
        except Exception:  # noqa: BLE001 - fail closed without exposing private coordinator errors
            self.stopped = "EXECUTION_AUTHORIZATION_FAILED"
            return False

    async def _observe(self, observation):
        if monotonic() >= self.deadline_at:
            # No control request has begun. An already-observed local wall cutoff
            # is not evidence that a coordinator acknowledgment was lost.
            self.stopped = self.stopped or "DEADLINE_EXCEEDED"
            return
        try:
            async with asyncio.timeout_at(self.deadline_at):
                if await self.lifecycle.observe(observation) is not True:
                    raise ValueError("observation not acknowledged")
        except (LifecycleUncertainty, TimeoutError):
            self.interruption = "COORDINATOR_ACK_UNCERTAIN"
            self.stopped = "EXECUTION_ACK_FAILED"
        except Exception:  # noqa: BLE001 - explicit refusal stops subsequent work
            self.stopped = "EXECUTION_ACK_FAILED"

    async def refresh(self, *, candidates_cursor="0", events_cursor="0"):
        ordinal = self.host_reads + 1
        ref = f"host-context-{ordinal}"
        command = build_command("read_case_context", {"invocation_id": self.invocation_id,
            "candidates_cursor": candidates_cursor, "events_cursor": events_cursor})
        if not await self._authorize(ExecutionRequest("context", ordinal, self.invocation_id,
                                                      call_ref=ref, command=command)):
            return None
        self.host_reads = ordinal
        try:
            async with asyncio.timeout_at(self.deadline_at):
                result = await self.client.execute(command, call_ref=ref)
            uncertainty = getattr(self.client, "uncertainty", None)
            if isinstance(uncertainty, LifecycleUncertainty):
                self.interruption = uncertainty.kind
            if result["outcome"] != "OK":
                raise ValueError("context unavailable")
            case = CaseContext.model_validate_json(json.dumps(result["data"]))
            if case.invocation_id != self.invocation_id:
                raise ValueError("context identity mismatch")
        except Exception:  # noqa: BLE001 - safe failure boundary around injected transport
            await self._observe(ExecutionObservation("context", ordinal, self.invocation_id,
                                                      "ERROR", call_ref=ref))
            self.stopped = self.stopped or "CONTEXT_UNAVAILABLE"
            return None
        await self._observe(ExecutionObservation("context", ordinal, self.invocation_id,
                                                  "OK", call_ref=ref))
        if self.stopped:
            return None
        self.case = case
        if case.saved_stop:
            self.stopped = case.saved_stop
        return case

    async def before_model(self, event):
        if self.model_cycles >= 12:
            self.stopped = "MODEL_CYCLE_LIMIT"
        if self.stopped:
            event.cancel = self.stopped
            return
        case = await self.refresh()
        if case is None or self.stopped:
            event.cancel = self.stopped or "CONTEXT_UNAVAILABLE"
            return
        if not await self._authorize(ExecutionRequest("model", self.model_cycles + 1,
                                                      self.invocation_id, case=case)):
            event.cancel = self.stopped
            return
        self.model_cycles += 1
        self._model_started = monotonic()
        if self._deadline_handle is None and math.isfinite(self.deadline_at):
            self._deadline_handle = asyncio.get_running_loop().call_at(self.deadline_at, event.agent.cancel)
        event.agent.system_prompt = case_prompt(case)

    async def after_model(self, event):
        outcome = "ERROR" if event.exception else event.stop_response.stop_reason if event.stop_response else "UNKNOWN"
        visible = []
        if event.stop_response:
            for block in getattr(event.stop_response, "message", {}).get("content", [])[:40]:
                # Never persist hidden reasoning/reasoningContent or provider internals.
                if "text" in block:
                    visible.append({"text": block["text"][:2000]})
                elif "toolUse" in block:
                    tool = block["toolUse"]
                    visible.append({"toolUse": {"name": tool.get("name"), "input": tool.get("input")}})
        await self._observe(ExecutionObservation("model", self.model_cycles, self.invocation_id, outcome,
            result_json=json.dumps({"content": visible}, allow_nan=False),
            elapsed_ms=max(0, int((monotonic() - getattr(self, "_model_started", monotonic())) * 1000))))

    async def before_tool(self, event):
        self.tool_requests += 1
        if self.tool_requests > 40:
            self.stopped = "TOOL_REQUEST_LIMIT"
        if self.stopped:
            event.cancel_tool = self.stopped
            return
        try:
            if event.tool_use["name"] not in OPERATIONS:
                raise ValueError("unregistered model tool")
            command = build_command(event.tool_use["name"], event.tool_use["input"])
        except (ValueError, KeyError, TypeError):
            await self._authorize(ExecutionRequest("tool", self.tool_requests, self.invocation_id,
                call_ref=event.tool_use.get("toolUseId"), case=self.case))
            self.stopped = self.stopped or "INVALID_TOOL_INPUT"
            event.cancel_tool = "INVALID_TOOL_INPUT"
            return
        allowed = await self._authorize(ExecutionRequest("tool", self.tool_requests, self.invocation_id,
            call_ref=event.tool_use["toolUseId"], command=command, case=self.case))
        if not allowed:
            event.cancel_tool = self.stopped

    async def after_tool(self, event):
        uncertainty = getattr(self.client, "uncertainty", None)
        if isinstance(uncertainty, LifecycleUncertainty):
            self.interruption = uncertainty.kind
            self.stopped = "EXECUTION_ACK_FAILED"
        result = next((block["json"] for block in event.result.get("content", []) if "json" in block), None)
        outcome = result.get("outcome", "ERROR") if isinstance(result, dict) else "CANCELLED" if event.cancel_message else "ERROR"
        await self._observe(ExecutionObservation("tool", self.tool_requests, self.invocation_id, outcome,
            call_ref=event.tool_use.get("toolUseId"), result_json=json.dumps(result) if result is not None else None))
        if not self.stopped and isinstance(result, dict) and result.get("event_ids"):
            # Actual saved effect, not proposed intent or outcome text, decides stop.
            await self.refresh()
        if outcome == "ERROR" and event.tool_use.get("name") in {"inspect_completion", "inspect_intake_photo"}:
            self.stopped = self.stopped or "INSPECTION_UNRESOLVED"
        elif outcome == "ERROR":
            self.stopped = self.stopped or "TOOL_REQUEST_FAILED"

    async def after_tools(self, event):
        if self.stopped:
            event.end_turn = True

    async def after_invocation(self, event):
        if self._deadline_handle:
            self._deadline_handle.cancel()
        if self.provider:
            self.provider.close()
        try:
            summary = event.agent.event_loop_metrics.get_summary().get("accumulated_usage", {})
            self.usage = ModelUsage(**{k: v for k, v in summary.items() if k in ModelUsage.model_fields})
        except (ValueError, TypeError, AttributeError):
            self.usage = None
        await self._observe(ExecutionObservation("invocation", self.model_cycles, self.invocation_id,
            self.stopped or "MODEL_END_WITHOUT_SAVED_STOP", usage=self.usage))


def build_model() -> BedrockModel:
    """Frozen finite text-provider settings; no implicit SDK/Strands retries."""
    if (type(settings.temperature) not in (int, float) or not math.isfinite(settings.temperature)
            or not 0 <= settings.temperature <= 1):
        raise ValueError("model temperature must be a finite number between 0 and 1")
    if (type(settings.max_output_tokens) is not int or not 1 <= settings.max_output_tokens <= 8192
            or not math.isfinite(settings.provider_timeout_seconds)
            or not 0 < settings.provider_timeout_seconds <= 120):
        raise ValueError("invalid model execution bounds")
    kwargs = {"model_id": settings.resolved_text_model_id, "temperature": settings.temperature,
        "max_tokens": settings.max_output_tokens, "boto_client_config": Config(
            connect_timeout=min(10, settings.provider_timeout_seconds),
            read_timeout=settings.provider_timeout_seconds, retries={"total_max_attempts": 1})}
    if settings.aws_profile:
        import boto3
        kwargs["boto_session"] = boto3.Session(profile_name=settings.aws_profile, region_name=settings.region)
    else:
        kwargs["region_name"] = settings.region
    return BedrockModel(**kwargs)


def build_agent(session: InvocationToolSession, *, model=None, lifecycle=None,
                provider_observer=None, deadline_at=None) -> Agent:
    """Construct one fresh agent for one trusted session. Caller owns async closure.

    No arbitrary conversation/system override and no default printing callback.
    B12 supplies durable lifecycle controls; this factory alone is not a runner.
    """
    deadline = min(session.client._deadline_at, deadline_at) if deadline_at is not None else session.client._deadline_at
    model = model if model is not None else build_model()
    observer = ProviderObserver(model, session.client.transport.invocation_id, provider_observer)
    hooks = InvocationHooks(session.client, deadline_at=deadline, lifecycle=lifecycle, provider=observer)
    agent = Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=list(session.tools),
        tool_executor=SequentialToolExecutor(), callback_handler=None, retry_strategy=None,
        concurrent_invocation_mode="throw", hooks=[hooks])
    observer.start()
    agent.steward_hooks = hooks
    agent.steward_versions = {"prompt_version": PROMPT_VERSION, "tool_schema_version": SCHEMA_VERSION,
        "text_model_id": settings.resolved_text_model_id, "vision_model_id": settings.resolved_vision_model_id}
    return agent


class CaseExecutionResult(Record):
    invocation_id: Text
    saved_stop: Text | None
    error_code: Text | None
    sdk_stop_reason: Text | None
    model_cycles: int
    tool_requests: int
    host_reads: int
    sdk_pre_send_observations: int
    usage: ModelUsage | None
    interruption: UncertaintyKind | None = None


async def invoke_case(agent: Agent) -> CaseExecutionResult:
    """Bounded in-process execution, never an alternate durable runtime.

    Cancellation may detach an SDK worker; this result makes no zero-cost or
    remote-cancellation claim. B12 must retain uncertainty and fence late writes.
    """
    hooks = agent.steward_hooks
    error = None
    sdk_stop = None
    try:
        async with asyncio.timeout_at(hooks.deadline_at):
            result = await agent.invoke_async("Process the authentic saved trigger using the current case and tools.")
        sdk_stop = result.stop_reason
    except TimeoutError:
        agent.cancel()
        error = "DEADLINE_EXCEEDED"
    except asyncio.CancelledError:
        agent.cancel()
        raise
    except Exception as failure:  # noqa: BLE001 - no raw provider/SDK errors in public execution results
        # The public result stays opaque; the operator log keeps the provider/SDK failure class for diagnosis.
        logger.warning("invocation %s agent execution failed: %s: %s",
                       hooks.invocation_id, type(failure).__name__, failure)
        error = "AGENT_EXECUTION_FAILED"
    finally:
        hooks.provider.close()
        if hooks._deadline_handle:
            hooks._deadline_handle.cancel()
    saved_stop = hooks.case.saved_stop if hooks.case else None
    if saved_stop is None and error is None:
        error = hooks.stopped or "MODEL_END_WITHOUT_SAVED_STOP"
    return CaseExecutionResult(invocation_id=hooks.invocation_id, saved_stop=saved_stop,
        error_code=error, sdk_stop_reason=sdk_stop, model_cycles=hooks.model_cycles,
        tool_requests=hooks.tool_requests, host_reads=hooks.host_reads,
        sdk_pre_send_observations=hooks.provider.ordinal, usage=hooks.usage, interruption=hooks.interruption)
