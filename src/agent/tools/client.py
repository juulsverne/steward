"""One bounded, fixed-origin HTTP transport per trusted saved invocation."""

from __future__ import annotations

import asyncio
import json
import math
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from urllib.parse import urlsplit

import httpx

from .lifecycle import (
    AttemptObservation,
    AttemptPermit,
    CompletionAck,
    InMemoryRequestLifecycle,
    LifecycleError,
    LifecycleUncertainty,
    PreparedRequest,
    RequestLifecycle,
)
from .protocol import Command
from .protocol import error as _error
from .protocol import validated_envelope as _validated_envelope

__all__ = [
    "AttemptObservation",
    "AttemptPermit",
    "Command",
    "CompletionAck",
    "InMemoryRequestLifecycle",
    "PreparedRequest",
    "RequestLifecycle",
    "StewardHttpClient",
    "TrustedTransport",
]
MAX_RESPONSE_BYTES = 256 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


@dataclass(frozen=True)
class TrustedTransport:
    """Private settings; invocation identity must come from saved server context."""

    origin: str
    service_token: str = field(repr=False)
    invocation_id: str | None = None
    timeout_seconds: float = 20.0
    deadline_seconds: float = 120.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.origin)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(char.isspace() or ord(char) < 32 for char in self.origin)
        ):
            raise ValueError(
                "trusted origin must be an absolute origin without extra URL components"
            )
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("invalid origin port")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("plaintext transport is limited to local development")
        if (
            type(self.service_token) is not str
            or not self.service_token
            or len(self.service_token) > 4096
            or not self.service_token.isascii()
            or any(ord(char) <= 32 or ord(char) == 127 for char in self.service_token)
        ):
            raise ValueError("invalid service credential")
        if type(self.invocation_id) is not str or not _ID.fullmatch(self.invocation_id):
            raise ValueError("saved invocation identity is required")
        for value in (self.timeout_seconds, self.deadline_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 120:
                raise ValueError(
                    "transport limits must be finite, positive and at most 120 seconds"
                )


class StewardHttpClient:
    def __init__(
        self,
        transport: TrustedTransport,
        *,
        lifecycle: RequestLifecycle | None = None,
        lifecycle_factory: Callable[[StewardHttpClient], RequestLifecycle] | None = None,
        client: httpx.AsyncClient | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
        deadline_at: float | None = None,
    ) -> None:
        if lifecycle is not None and lifecycle_factory is not None:
            raise ValueError("choose one lifecycle provider")
        if client is not None and http_transport is not None:
            raise ValueError("choose one HTTP test injection")
        self.transport = transport
        self._deadline_at = monotonic() + transport.deadline_seconds
        if deadline_at is not None:
            if type(deadline_at) not in (int, float) or not math.isfinite(deadline_at):
                raise ValueError("invalid trusted absolute deadline")
            self._deadline_at = min(self._deadline_at, deadline_at)
        if client is not None and not _same_origin(client.base_url, httpx.URL(transport.origin)):
            raise ValueError("injected client origin differs")
        self._client = client or httpx.AsyncClient(
            base_url=transport.origin,
            follow_redirects=False,
            trust_env=False,
            verify=True,
            transport=http_transport,
            timeout=httpx.Timeout(
                transport.timeout_seconds,
                connect=min(10, transport.timeout_seconds),
                read=transport.timeout_seconds,
                write=transport.timeout_seconds,
                pool=min(10, transport.timeout_seconds),
            ),
        )
        self._owned_client = client is None
        self._closed = False
        self._locks: dict[str, asyncio.Lock] = {}
        self._unacknowledged: dict[str, AttemptObservation] = {}
        self.uncertainty: LifecycleUncertainty | None = None
        self.lifecycle = (
            lifecycle_factory(self)
            if lifecycle_factory
            else lifecycle or InMemoryRequestLifecycle()
        )
        if isinstance(self.lifecycle, InMemoryRequestLifecycle):
            self.lifecycle.bind(self, self._deadline_at)

    async def aclose(self) -> None:
        self._closed = True
        if self._owned_client:
            await self._client.aclose()

    async def host_request(self, operation: str) -> dict:
        """Fixed CLI status/context/wakeup reads, without pretending to hold an execution lease."""
        if operation not in {"context", "status", "resume"}:
            raise ValueError("unknown host operation")
        suffix = "" if operation == "status" else "/" + operation
        path = f"/api/invocations/{self.transport.invocation_id}{suffix}"
        deadline = min(self._deadline_at, monotonic() + 20)
        async with asyncio.timeout_at(deadline):
            async with self._client.stream("POST" if operation == "resume" else "GET", path,
                headers={"Authorization": f"Bearer {self.transport.service_token}",
                         "X-Steward-Invocation-Id": self.transport.invocation_id,
                         "Accept-Encoding": "identity"}, follow_redirects=False) as response:
                if response.is_redirect or response.headers.get("Content-Encoding", "identity") != "identity":
                    return _error("UNTRUSTED_RESPONSE")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        return _error("RESPONSE_TOO_LARGE")
                from ..case_contracts import CaseContext
                from ..contracts import ToolResult
                from ..runtime_contracts import RuntimeStatus
                try:
                    model = CaseContext if operation == "context" else RuntimeStatus
                    return ToolResult[model].model_validate_json(raw).model_dump(mode="json")
                except ValueError:
                    return _error("INVALID_RESPONSE")

    async def execute(self, command: Command, *, call_ref: str | None = None) -> dict:
        if not isinstance(command, Command):
            return _error("INVALID_COMMAND")
        call_ref = call_ref or "call-" + secrets.token_hex(16)
        if (
            type(call_ref) is not str
            or not 1 <= len(call_ref) <= 200
            or any(ord(x) < 32 for x in call_ref)
        ):
            return _error("INVALID_CALL_REFERENCE")
        return await self._run(command=command, call_ref=call_ref)

    async def recover(self, logical_request_id: str) -> dict:
        """Private recovery, never a model-visible tool."""
        if type(logical_request_id) is not str or not _ID.fullmatch(logical_request_id):
            return _error("INVALID_LOGICAL_REQUEST")
        return await self._run(logical_request_id=logical_request_id)

    async def _run(self, *, command=None, call_ref=None, logical_request_id=None) -> dict:
        if self._closed:
            return _error("SESSION_CLOSED")
        try:
            async with asyncio.timeout_at(self._deadline_at):
                prepared = (
                    await self.lifecycle.prepare(call_ref, command)
                    if command is not None
                    else await self.lifecycle.load(logical_request_id)
                )
                self._validate_prepared(prepared, command)
                async with self._locks.setdefault(prepared.logical_request_id, asyncio.Lock()):
                    prepared = await self.lifecycle.load(prepared.logical_request_id)
                    self._validate_prepared(prepared, command)
                    return await self._drive(prepared)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            if self._unacknowledged:
                self.uncertainty = LifecycleUncertainty("LIFECYCLE_ACK_UNCERTAIN", "COORDINATOR_ACK_UNCERTAIN")
            return _error("DEADLINE_EXCEEDED")
        except LifecycleError as exc:
            if isinstance(exc, LifecycleUncertainty):
                self.uncertainty = exc
            safe_codes = {
                "LOGICAL_REQUEST_CONFLICT",
                "LOGICAL_REQUEST_NOT_FOUND",
                "ATTEMPT_UNRESOLVED",
                "ATTEMPTS_EXHAUSTED",
                "DEADLINE_EXCEEDED",
                "LIFECYCLE_ACK_UNCERTAIN",
            }
            return _error(exc.code if exc.code in safe_codes else "LIFECYCLE_ERROR")
        except Exception:  # noqa: BLE001 - never expose private lifecycle backend exceptions
            return _error("LIFECYCLE_ERROR")

    def _validate_prepared(self, prepared: PreparedRequest, command: Command | None) -> None:
        if (
            not isinstance(prepared, PreparedRequest)
            or not _ID.fullmatch(prepared.logical_request_id)
            or (command is not None and prepared.command != command)
            or not isinstance(prepared.command, Command)
            or prepared.invocation_id != self.transport.invocation_id
            or type(prepared.deadline_at) not in (int, float)
            or not math.isfinite(prepared.deadline_at)
            or prepared.deadline_at > self._deadline_at
        ):
            raise LifecycleError("INVALID_PREPARED_REQUEST")
        if prepared.command.mutation:
            if type(prepared.idempotency_key) is not str or not _KEY.fullmatch(
                prepared.idempotency_key
            ):
                raise LifecycleError("INVALID_PREPARED_REQUEST")
        elif prepared.idempotency_key is not None:
            raise LifecycleError("INVALID_PREPARED_REQUEST")

    async def _ack(self, observation: AttemptObservation) -> None:
        try:
            ack = await self.lifecycle.finish_attempt(observation.attempt_id, observation)
            if (
                not isinstance(ack, CompletionAck)
                or not ack.accepted
                or ack.attempt_id != observation.attempt_id
                or ack.logical_request_id != observation.logical_request_id
            ):
                raise LifecycleUncertainty("LIFECYCLE_ACK_UNCERTAIN", "COORDINATOR_ACK_UNCERTAIN")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - acknowledgment loss must remain a safe uncertain result
            raise LifecycleUncertainty("LIFECYCLE_ACK_UNCERTAIN", "COORDINATOR_ACK_UNCERTAIN") from None
        self._unacknowledged.pop(observation.logical_request_id, None)

    async def _drive(self, prepared: PreparedRequest) -> dict:
        while True:
            pending = self._unacknowledged.get(prepared.logical_request_id)
            if pending is not None:
                await self._ack(pending)
            prepared = await self.lifecycle.load(prepared.logical_request_id)
            self._validate_prepared(prepared, None)
            if prepared.terminal_json is not None:
                return _validated_envelope(prepared.terminal_result, prepared.command.operation)
            if monotonic() >= min(self._deadline_at, prepared.deadline_at):
                return _error("DEADLINE_EXCEEDED")
            permit = await self.lifecycle.begin_attempt(prepared.logical_request_id)
            self._validate_permit(permit, prepared)
            observation = await self._attempt(prepared, permit)
            self._unacknowledged[prepared.logical_request_id] = observation
            await self._ack(observation)
            if not observation.retryable or permit.ordinal >= 3:
                return observation.result
            remaining = min(self._deadline_at, prepared.deadline_at) - monotonic()
            if remaining <= 0:
                return _error("DEADLINE_EXCEEDED")
            await asyncio.sleep(min(0.02 * permit.ordinal, remaining))

    def _validate_permit(self, permit: AttemptPermit, prepared: PreparedRequest) -> None:
        if (
            not isinstance(permit, AttemptPermit)
            or permit.logical_request_id != prepared.logical_request_id
            or not _ID.fullmatch(permit.attempt_id)
            or type(permit.ordinal) is not int
            or not 1 <= permit.ordinal <= 3
            or type(permit.deadline_at) not in (int, float)
            or not math.isfinite(permit.deadline_at)
            or permit.deadline_at > min(self._deadline_at, prepared.deadline_at)
            or permit.deadline_at <= monotonic()
        ):
            raise LifecycleError("INVALID_ATTEMPT_PERMIT")
        if (permit.lease_owner is None) != (permit.fencing_token is None):
            raise LifecycleError("INVALID_ATTEMPT_PERMIT")
        if permit.lease_owner is not None and (
            not _ID.fullmatch(permit.lease_owner)
            or type(permit.fencing_token) is not int
            or permit.fencing_token < 0
        ):
            raise LifecycleError("INVALID_ATTEMPT_PERMIT")

    async def _attempt(
        self, prepared: PreparedRequest, permit: AttemptPermit
    ) -> AttemptObservation:
        started = monotonic()
        command = prepared.command
        headers = {
            "Authorization": f"Bearer {self.transport.service_token}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "X-Steward-Invocation-Id": self.transport.invocation_id,
            "X-Steward-Attempt-Id": permit.attempt_id,
        }
        if prepared.idempotency_key is not None:
            headers["Idempotency-Key"] = prepared.idempotency_key
        if command.expected_revision is not None:
            headers["X-Steward-Expected-Revision"] = str(command.expected_revision)
        if permit.lease_owner is not None:
            headers["X-Steward-Lease-Owner"] = permit.lease_owner
            headers["X-Steward-Fencing-Token"] = str(permit.fencing_token)
        if command.body_json is not None:
            headers["Content-Type"] = "application/json"
        status = None
        request_id = None
        send_state = "not_sent"
        result = _error("TRANSPORT_ERROR")
        transport_uncertain = False
        disposition_known = False

        def observed(cancelled=False):
            return AttemptObservation(
                permit.attempt_id,
                prepared.logical_request_id,
                json.dumps(result, allow_nan=False, sort_keys=True),
                status,
                request_id,
                max(0, int((monotonic() - started) * 1000)),
                send_state,
                _retryable(result)
                and (
                    transport_uncertain
                    or (
                        status == 503
                        and command.operation in {"inspect_completion", "inspect_intake_photo"}
                        and result["reason_code"] == "INSPECTION_IN_PROGRESS"
                    )
                ),
                cancelled,
            )

        try:
            request = self._client.build_request(
                command.method,
                command.path,
                params=command.query,
                content=command.body_json.encode() if command.body_json is not None else None,
                headers=headers,
            )
            if not _same_origin(request.url, httpx.URL(self.transport.origin)):
                return observed()
            remaining = min(permit.deadline_at, self._deadline_at) - monotonic()
            attempt_deadline = monotonic() + min(self.transport.timeout_seconds, remaining * 0.95)
            async with asyncio.timeout_at(attempt_deadline):
                send_state = "may_have_been_sent"
                response = await self._client.send(request, stream=True, follow_redirects=False)
                try:
                    status = response.status_code
                    send_state = "response_received"
                    response_id = response.headers.get("X-Request-ID")
                    request_id = response_id if response_id and _ID.fullmatch(response_id) else None
                    if response.is_redirect or not _same_origin(
                        response.url, httpx.URL(self.transport.origin)
                    ):
                        result = _error("UNTRUSTED_REDIRECT")
                        disposition_known = True
                    elif response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        result = _error("UNSUPPORTED_RESPONSE_ENCODING")
                        disposition_known = True
                    else:
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                                result = _error("RESPONSE_TOO_LARGE")
                                disposition_known = True
                                break
                            data.extend(chunk)
                        else:
                            try:
                                payload = json.loads(data)
                            except (ValueError, UnicodeError, RecursionError):
                                result = _error("MALFORMED_RESPONSE")
                            else:
                                result = _validated_envelope(payload, command.operation, status)
                            disposition_known = True
                finally:
                    await response.aclose()
        except asyncio.CancelledError:
            if not disposition_known:
                result = _error("TRANSPORT_UNCERTAIN")
                transport_uncertain = True
            observation = observed(cancelled=True)
            self._unacknowledged[prepared.logical_request_id] = observation
            # Preserve known outcomes; only incomplete sends remain uncertain.
            cleanup_budget = min(0.05, max(0, self._deadline_at - monotonic()))
            if cleanup_budget <= 0:
                raise
            cleanup = asyncio.create_task(self._ack(observation))
            try:
                await asyncio.wait_for(asyncio.shield(cleanup), timeout=cleanup_budget)
            except (Exception, asyncio.CancelledError):  # noqa: BLE001 - bounded cancellation cleanup
                cleanup.cancel()
                await asyncio.gather(cleanup, return_exceptions=True)
            raise
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError):
            if not disposition_known:
                result = _error("TRANSPORT_UNCERTAIN")
                transport_uncertain = True
        except Exception:  # noqa: BLE001 - the transport boundary must sanitize arbitrary failures
            if not disposition_known:
                result = _error("TRANSPORT_ERROR")
        return observed()


def _same_origin(left: httpx.URL, right: httpx.URL) -> bool:
    return (left.scheme, left.host, left.port) == (right.scheme, right.host, right.port)


def _retryable(result: dict) -> bool:
    return result["outcome"] == "ERROR" and result["reason_code"] in {
        "TRANSPORT_UNCERTAIN",
        "INSPECTION_IN_PROGRESS",
    }
