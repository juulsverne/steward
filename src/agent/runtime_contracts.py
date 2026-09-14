"""Private coordinator wire records. No provider, database or tool SDK imports."""
from typing import Literal

from . import contracts as c


class Claim(c.Record):
    invocation_id: c.OpaqueId
    owner: c.OpaqueId
    fence: c.Positive
    episode: c.Positive
    deadline: c.Timestamp
    server_time: c.Timestamp
    model_cycles: c.Nonnegative = 0
    tool_requests: c.Nonnegative = 0


class CommandRecord(c.Record):
    operation: c.Text
    method: Literal["GET", "POST"]
    path: c.Text
    query: dict[str, str]
    body_json: str | None
    expected_revision: c.Nonnegative | None
    schema_version: c.Text


def command_record(command):
    return CommandRecord(operation=command.operation, method=command.method, path=command.path,
        query=command.query, body_json=command.body_json, expected_revision=command.expected_revision,
        schema_version=command.schema_version)


def restored_command(record):
    import json

    from .tools.protocol import SCHEMA_VERSION, Command
    if record.schema_version != SCHEMA_VERSION:
        raise ValueError("COMMAND_VERSION_CHANGED")
    return Command(record.operation, record.method, record.path, query=record.query,
        body=None if record.body_json is None else json.loads(record.body_json),
        expected_revision=record.expected_revision)


class LogicalRequest(c.Record):
    id: c.OpaqueId
    invocation_id: c.OpaqueId
    call_ref: c.OpaqueId
    command: CommandRecord
    idempotency_key: c.Text | None
    deadline: c.Timestamp
    created_at: c.Timestamp
    terminal_json: str | None = None
    receipt_id: c.Text | None = None


class RuntimeAttempt(c.Record):
    id: c.OpaqueId
    logical_request_id: c.OpaqueId
    owner: c.OpaqueId
    fence: c.Positive
    ordinal: c.Positive
    deadline: c.Timestamp
    created_at: c.Timestamp


class RuntimeControl(c.Record):
    nonce: c.OpaqueId
    claim: Claim | None = None
    owner: c.OpaqueId | None = None
    call_ref: c.OpaqueId | None = None
    command: CommandRecord | None = None
    logical_request_id: c.OpaqueId | None = None
    attempt_id: c.OpaqueId | None = None
    observation_json: str | None = None
    details_json: str | None = None
    kind: Literal["context", "model", "tool", "invocation", "sdk_before_send"] | None = None
    ordinal: c.Nonnegative | None = None
    outcome: c.Text | None = None
    status: Literal["WAITING", "COMPLETED", "ERROR"] | None = None


class ControlAck(c.Record):
    accepted: bool


class ControlReply(c.Record):
    data: Claim | LogicalRequest | RuntimeAttempt | ControlAck | tuple[LogicalRequest, ...]


class TransportObservation(c.Record):
    attempt_id: c.Text
    logical_request_id: c.Text
    result_json: str
    status_code: c.Nonnegative | None
    request_id: c.Text | None
    elapsed_ms: c.Nonnegative
    send_state: Literal["not_sent", "may_have_been_sent", "response_received"]
    retryable: bool
    cancelled: bool = False


class RuntimeTrace(c.Record):
    id: c.Positive
    kind: c.Text
    ordinal: c.Nonnegative
    phase: Literal["REQUESTED", "OBSERVED"]
    recorded_at: c.Text
    outcome: c.Text | None = None
    operation: c.Text | None = None
    arguments: dict | None = None
    result: dict | None = None
    usage: c.ModelUsage | None = None
    versions: dict | None = None
    policy_version: c.Text | None = None
    receipt_id: c.Text | None = None
    elapsed_ms: c.Nonnegative | None = None
    attempts: tuple[dict, ...] = ()
    content_truncated: bool = False


class RuntimeStatus(c.Record):
    invocation_id: c.Text
    trigger_event_id: c.Positive
    status: c.InvocationStatus
    state_revision: c.Nonnegative
    episode_count: c.Nonnegative
    model_cycles: c.Nonnegative
    tool_requests: c.Nonnegative
    logical_requests: c.Nonnegative
    transport_attempts: c.Nonnegative
    server_control_requests: c.Nonnegative = 0
    error_code: c.Text | None = None
    trace: tuple[RuntimeTrace, ...] = ()
    next_cursor: c.Nonnegative | None = None
    truncated: bool = False
