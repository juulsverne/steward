"""Durable lifecycle adapter; all persistence goes through the same owned HTTP client."""
import asyncio
import json
from dataclasses import asdict
from time import monotonic
from uuid import uuid4

import httpx

from ..runtime_contracts import (
    Claim,
    LogicalRequest,
    RuntimeAttempt,
    RuntimeControl,
    command_record,
    restored_command,
)
from .lifecycle import (
    AttemptPermit,
    CompletionAck,
    LifecycleError,
    LifecycleUncertainty,
    PreparedRequest,
)

CONTROL_OPERATIONS = frozenset(("claim", "renew", "prepare", "load", "begin", "finish", "reconcile",
                                "requests", "authorize", "observe", "complete"))


class DurableLifecycle:
    def __init__(self, client):
        self.client = client
        self.claim = None
        self.owner = str(uuid4())
        self.control_attempts = 0
        self.model_ordinal = 0
        self.tool_ordinal = 0
        self.tool_ref = None
        self.host_sequence = 0
        self.model_base = 0
        self.tool_base = 0

    async def control(self, operation, *, nonce=None, **values):
        if operation not in CONTROL_OPERATIONS:
            raise LifecycleError("UNKNOWN_CONTROL")
        body = RuntimeControl(nonce=nonce or str(uuid4()), claim=self.claim, **values).model_dump_json()
        started = monotonic()
        deadline = min(self.client._deadline_at, started + 20)
        if operation in {"complete", "observe", "finish", "reconcile"} and deadline <= started:
            deadline = started + 5  # bounded observation/reconciliation only; never a new execution permit
        # Fixed private control surface bypasses prepare/attempt interception; no second HTTP client.
        for _ in range(3):
            self.control_attempts += 1
            try:
                async with asyncio.timeout_at(deadline):
                    async with self.client._client.stream("POST",
                        f"/internal/invocations/{self.client.transport.invocation_id}/{operation}",
                        content=body, headers={"Authorization": f"Bearer {self.client.transport.service_token}",
                            "Content-Type": "application/json", "Accept-Encoding": "identity"}, follow_redirects=False) as response:
                        if response.is_redirect or response.headers.get("Content-Encoding", "identity") != "identity":
                            raise LifecycleError("UNTRUSTED_CONTROL_RESPONSE")
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 256 * 1024:
                                raise LifecycleError("CONTROL_RESPONSE_TOO_LARGE")
                        value = json.loads(raw)
                        if response.status_code != 200:
                            raise LifecycleError(value.get("reason_code", "COORDINATOR_REJECTED"))
                        return value["data"]
            except (httpx.TransportError, TimeoutError):
                if monotonic() >= deadline:
                    break
            except (ValueError, KeyError):
                raise LifecycleError("INVALID_CONTROL_RESPONSE") from None
        raise LifecycleUncertainty("CONTROL_UNRESOLVED")

    async def acquire(self):
        started = monotonic()
        self.claim = Claim.model_validate_json(json.dumps(await self.control("claim", owner=self.owner)))
        # Subtract the entire request elapsed time, conservatively including server processing.
        remaining = (self.claim.deadline - self.claim.server_time).total_seconds() - (monotonic() - started)
        self.client._deadline_at = min(self.client._deadline_at, monotonic() + max(0, remaining))
        self.model_ordinal, self.tool_ordinal = self.claim.model_cycles, self.claim.tool_requests
        self.model_base, self.tool_base = self.model_ordinal, self.tool_ordinal
        return self.claim

    def prepared(self, saved):
        # Logical requests retain their original UTC deadline across owner and episode changes.
        remaining = (saved.deadline - self.claim.server_time).total_seconds()
        deadline = min(self.client._deadline_at, self._claim_monotonic + remaining)
        return PreparedRequest(saved.id, saved.idempotency_key, restored_command(saved.command),
            deadline, saved.invocation_id, saved.terminal_json)

    @property
    def _claim_monotonic(self):
        return self.client._deadline_at - max(0, (self.claim.deadline - self.claim.server_time).total_seconds())

    async def prepare(self, call_ref, command):
        if command.operation == "read_case_context":
            self.host_sequence += 1
            ref = f"host-{self.claim.fence}-{self.host_sequence}"
        else:
            if self.tool_ref is None:
                raise LifecycleError("TOOL_EXECUTION_NOT_AUTHORIZED")
            ref = self.tool_ref
        value = await self.control("prepare", call_ref=ref, command=command_record(command))
        return self.prepared(LogicalRequest.model_validate_json(json.dumps(value)))

    async def load(self, logical_request_id):
        value = await self.control("load", logical_request_id=logical_request_id)
        return self.prepared(LogicalRequest.model_validate_json(json.dumps(value)))

    async def begin_attempt(self, logical_request_id):
        value = await self.control("begin", logical_request_id=logical_request_id)
        attempt = RuntimeAttempt.model_validate_json(json.dumps(value))
        remaining = (attempt.deadline - self.claim.server_time).total_seconds()
        return AttemptPermit(attempt.id, logical_request_id, attempt.ordinal,
            min(self.client._deadline_at, self._claim_monotonic + remaining), attempt.owner, attempt.fence)

    async def finish_attempt(self, attempt_id, observation):
        value = await self.control("finish", nonce=f"ack-{attempt_id}", attempt_id=attempt_id,
            observation_json=json.dumps(asdict(observation), sort_keys=True, allow_nan=False))
        return CompletionAck(attempt_id, observation.logical_request_id, value.get("accepted") is True)

    async def authorize(self, request):
        if request.kind == "model":
            self.model_ordinal += 1
            ordinal = self.model_ordinal
        elif request.kind == "tool":
            self.tool_ordinal += 1
            ordinal = self.tool_ordinal
            self.tool_ref = f"model-{self.model_ordinal}-tool-{ordinal}"
        else:
            ordinal = request.ordinal
        details = {"command": command_record(request.command).model_dump(mode="json") if request.command else None,
                   "configuration": request.case.configuration.model_dump(mode="json") if request.case and request.case.configuration else None,
                   "policy_version": request.case.policy.version if request.case and request.case.policy else None}
        return (await self.control("authorize", nonce=f"authorize-{self.claim.fence}-{request.kind}-{ordinal}",
            kind=request.kind, ordinal=ordinal, details_json=json.dumps(details, allow_nan=False))).get("accepted") is True

    async def observe(self, observation):
        ordinal = self.model_base + observation.ordinal if observation.kind == "model" else self.tool_base + observation.ordinal if observation.kind == "tool" else observation.ordinal
        value = {"outcome": observation.outcome, "result_json": observation.result_json,
                 "elapsed_ms": observation.elapsed_ms,
                 "usage": observation.usage.model_dump(mode="json") if observation.usage else None}
        return (await self.control("observe", nonce=f"observe-{self.claim.fence}-{observation.kind}-{ordinal}",
            kind=observation.kind, ordinal=ordinal, observation_json=json.dumps(value, allow_nan=False))).get("accepted") is True

    async def recover_unresolved(self):
        for value in await self.control("requests"):
            saved = LogicalRequest.model_validate_json(json.dumps(value))
            if saved.terminal_json is not None:
                continue
            saved = LogicalRequest.model_validate_json(json.dumps(await self.control("reconcile", logical_request_id=saved.id)))
            if saved.terminal_json is not None:
                continue
            prepared = self.prepared(saved)
            if prepared.deadline_at <= monotonic():
                raise LifecycleError("EXPIRED_REQUEST_UNRESOLVED")
            result = await self.client.recover(saved.id)
            if result.get("outcome") == "ERROR":
                raise LifecycleError("RECOVERY_UNRESOLVED")
