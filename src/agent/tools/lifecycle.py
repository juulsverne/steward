"""Private request/attempt protocol; Stage B supplies explicitly non-durable state."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, replace
from time import monotonic
from typing import Literal, Protocol

from .protocol import Command


class LifecycleError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


UncertaintyKind = Literal["COORDINATOR_ACK_UNCERTAIN", "COORDINATOR_CONTROL_UNCERTAIN"]


class LifecycleUncertainty(LifecycleError):
    """Private control disposition, never inferred from a model/domain error string."""
    def __init__(self, code: str, kind: UncertaintyKind = "COORDINATOR_CONTROL_UNCERTAIN"):
        self.kind = kind
        super().__init__(code)


@dataclass(frozen=True)
class PreparedRequest:
    logical_request_id: str
    idempotency_key: str | None
    command: Command
    deadline_at: float
    invocation_id: str | None = None
    terminal_json: str | None = None

    @property
    def terminal_result(self) -> dict | None:
        return None if self.terminal_json is None else json.loads(self.terminal_json)


@dataclass(frozen=True)
class AttemptPermit:
    attempt_id: str
    logical_request_id: str
    ordinal: int
    deadline_at: float
    lease_owner: str | None = None
    fencing_token: int | None = None


@dataclass(frozen=True)
class AttemptObservation:
    attempt_id: str
    logical_request_id: str
    result_json: str
    status_code: int | None
    request_id: str | None
    elapsed_ms: int
    send_state: Literal["not_sent", "may_have_been_sent", "response_received"]
    retryable: bool
    cancelled: bool = False

    @property
    def result(self) -> dict:
        return json.loads(self.result_json)


@dataclass(frozen=True)
class CompletionAck:
    attempt_id: str
    logical_request_id: str
    accepted: bool = True


class RequestLifecycle(Protocol):
    async def prepare(self, call_ref: str, command: Command) -> PreparedRequest: ...
    async def load(self, logical_request_id: str) -> PreparedRequest: ...
    async def begin_attempt(self, logical_request_id: str) -> AttemptPermit: ...
    async def finish_attempt(
        self, attempt_id: str, observation: AttemptObservation
    ) -> CompletionAck: ...


class InMemoryRequestLifecycle:
    """No disk/SQLite, restart recovery, leases or durable-ack claims are provided."""

    def __init__(self, *, deadline_at: float | None = None) -> None:
        self._deadline_at = deadline_at
        self._binding: object | None = None
        self._invocation_id: str | None = None
        self._calls: dict[str, str] = {}
        self._prepared: dict[str, PreparedRequest] = {}
        self._attempts: dict[str, list[AttemptPermit]] = {}
        self._observations: dict[str, AttemptObservation] = {}

    def bind(self, owner: object, deadline_at: float) -> None:
        if self._binding is not None and self._binding is not owner:
            raise ValueError("lifecycle cannot be shared between invocation clients")
        self._binding = owner
        self._invocation_id = owner.transport.invocation_id
        self._deadline_at = (
            min(self._deadline_at, deadline_at) if self._deadline_at is not None else deadline_at
        )

    async def prepare(self, call_ref: str, command: Command) -> PreparedRequest:
        if call_ref in self._calls:
            previous = self._prepared[self._calls[call_ref]]
            if previous.command != command:
                raise LifecycleError("LOGICAL_REQUEST_CONFLICT")
            return previous
        if self._deadline_at is None:
            self._deadline_at = monotonic() + 120
        logical_id = "logical-" + secrets.token_hex(16)
        prepared = PreparedRequest(
            logical_id,
            "steward-" + secrets.token_urlsafe(24) if command.mutation else None,
            command,
            self._deadline_at,
            invocation_id=self._invocation_id,
        )
        self._calls[call_ref] = logical_id
        self._prepared[logical_id] = prepared
        self._attempts[logical_id] = []
        return prepared

    async def load(self, logical_request_id: str) -> PreparedRequest:
        try:
            return self._prepared[logical_request_id]
        except KeyError:
            raise LifecycleError("LOGICAL_REQUEST_NOT_FOUND") from None

    async def begin_attempt(self, logical_request_id: str) -> AttemptPermit:
        prepared = await self.load(logical_request_id)
        attempts = self._attempts[logical_request_id]
        if prepared.terminal_json is not None:
            raise LifecycleError("LOGICAL_REQUEST_TERMINAL")
        if any(attempt.attempt_id not in self._observations for attempt in attempts):
            raise LifecycleError("ATTEMPT_UNRESOLVED")
        if len(attempts) >= 3:
            raise LifecycleError("ATTEMPTS_EXHAUSTED")
        if monotonic() >= prepared.deadline_at:
            raise LifecycleError("DEADLINE_EXCEEDED")
        permit = AttemptPermit(
            "attempt-" + secrets.token_hex(16),
            logical_request_id,
            len(attempts) + 1,
            prepared.deadline_at,
        )
        attempts.append(permit)
        return permit

    async def finish_attempt(
        self, attempt_id: str, observation: AttemptObservation
    ) -> CompletionAck:
        prepared = await self.load(observation.logical_request_id)
        attempts = self._attempts[observation.logical_request_id]
        if observation.attempt_id != attempt_id or not any(
            attempt.attempt_id == attempt_id for attempt in attempts
        ):
            raise LifecycleError("ATTEMPT_IDENTITY_MISMATCH")
        old = self._observations.get(attempt_id)
        if old is not None and old != observation:
            raise LifecycleError("ATTEMPT_OBSERVATION_CONFLICT")
        self._observations[attempt_id] = observation
        if not observation.retryable or len(attempts) >= 3 or monotonic() >= prepared.deadline_at:
            self._prepared[prepared.logical_request_id] = replace(
                prepared, terminal_json=observation.result_json
            )
        return CompletionAck(attempt_id, prepared.logical_request_id)
