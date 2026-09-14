"""Independent B10B frozen review repros. Run only with pre-import offline_guard."""

import asyncio
from time import monotonic

import httpx
import pytest

from agent.tools.client import (
    Command,
    InMemoryRequestLifecycle,
    StewardHttpClient,
    TrustedTransport,
    _validated_envelope,
)
from agent.tools.durable import DurableLifecycle
from agent.tools.steward import OPERATIONS, StewardAgentTool

ORIGIN = "http://127.0.0.1:8123"


def envelope(data=None, outcome="OK", reason=None):
    return {
        "outcome": outcome,
        "reason_code": reason,
        "data": data,
        "unmet": [],
        "allowed_next": [],
        "evidence_ids": [],
        "event_ids": [],
    }


def command():
    return Command(
        "dispatch_vendor",
        "POST",
        "/api/plans/plan/dispatch",
        body={"vendor_id": "vendor"},
        expected_revision=2,
        mutation=True,
    )


class Spy:
    def __init__(self):
        self.calls = []

    async def execute(self, command, *, call_ref):
        self.calls.append(command)
        return envelope({"record_id": "record", "state_revision": 0})


async def invoke(tool, data, ref="call-1"):
    life = getattr(tool.client, "lifecycle", None)
    if isinstance(life, DurableLifecycle):
        from agent.core import ExecutionRequest
        from agent.tools.protocol import build_command
        await life.acquire()
        await life.authorize(ExecutionRequest("model", 1, life.claim.invocation_id))
        await life.authorize(ExecutionRequest("tool", 1, life.claim.invocation_id,
            command=build_command(tool.tool_name, data)))
    events = [
        x async for x in tool.stream({"toolUseId": ref, "name": tool.tool_name, "input": data}, {})
    ]
    return events[-1].tool_result["content"][0]["json"]


def test_sdk_tool_spec_has_required_json_container():
    spec = StewardAgentTool("find_related_signals", Spy()).tool_spec
    assert set(spec["inputSchema"]) == {"json"}


def test_all_thirteen_architecture_tools_include_escalation():
    assert "escalate_to_operator" in OPERATIONS


@pytest.mark.asyncio
async def test_full_classification_proposal_can_reach_transport():
    spy = Spy()
    data = {
        "issue_id": "issue",
        "signal_id": "signal",
        "category": "bulky_waste",
        "expected_issue_revision": 1,
        "visible_objects": ["couch"],
        "hazards": [],
        "primary_target": "brown couch",
        "full_cleanup_scope": "couch and bags",
        "marked_work_area": "sidewalk",
        "large_object_count": 1,
        "supporting_evidence_ids": ["image"],
        "unknowns": [],
    }
    result = await invoke(StewardAgentTool("classify_issue", spy), data)
    assert result["outcome"] == "OK", result
    assert spy.calls[0].body["primary_target"] == "brown couch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,data",
    [
        (
            "determine_jurisdiction",
            {
                "issue_id": "issue",
                "classification_fact_id": "fact",
                "responsibility": "pay_everyone",
                "expected_issue_revision": 1,
            },
        ),
        (
            "record_operational_decision",
            {
                "issue_id": "issue",
                "decision_type": "RESOLVE",
                "summary": "resolve",
                "basis": {"kind": "resolve", "actor_id": "forged"},
                "expected_issue_revision": 1,
            },
        ),
    ],
)
async def test_bad_shared_dto_inputs_are_rejected_before_transport(name, data):
    spy = Spy()
    result = await invoke(StewardAgentTool(name, spy), data)
    assert spy.calls == [], result


@pytest.mark.parametrize(
    "name,data",
    [
        ("request_rework", {"decision_id": "decision", "expected_job_revision": 4}),
        ("inspect_intake_photo", {"signal_id": "signal"}),
    ],
)
def test_bodyless_registry_commands_do_not_retain_path_ids(name, data):
    tool = StewardAgentTool(name, Spy())
    assert tool._command(data).body is None


@pytest.mark.parametrize(
    "operation,data",
    [
        ("get_job", {"id": 5, "issue_id": False, "state_revision": -8, "proof_requirements": "bad"}),
        (
            "inspect_completion",
            {
                "kind": "completion_inspection",
                "attempt_id": "attempt",
                "job_id": "job",
                "submission_id": "proof",
            },
        ),
        ("record_operational_decision", {"kind": "operational_decision", "decision": {}}),
    ],
)
def test_malformed_typed_success_is_not_accepted(operation, data):
    result = _validated_envelope(envelope(data), operation)
    assert result["outcome"] == "ERROR", result


def test_bad_denial_data_and_event_ids_are_not_passed_through():
    value = envelope({"untrusted": "raw"}, outcome="DENIED", reason="DENIED")
    value["event_ids"] = ["not-an-event", {}]
    assert _validated_envelope(value, "release_payment")["outcome"] == "ERROR"


@pytest.mark.asyncio
async def test_same_logical_request_does_not_regain_three_attempts():
    calls = []

    async def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("unknown", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=ORIGIN) as http:
        client = StewardHttpClient(
            TrustedTransport(ORIGIN, "token", invocation_id="invoke"), client=http
        )
        await client.execute(command(), call_ref="one")
        await client.execute(command(), call_ref="one")
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_terminal_logical_result_is_reused_without_another_send():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(
            403,
            json=envelope(
                {"record_id": "job", "state_revision": 4}, "DENIED", "COMPLETION_GATES_UNMET"
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=ORIGIN) as http:
        client = StewardHttpClient(
            TrustedTransport(ORIGIN, "token", invocation_id="invoke"), client=http
        )
        first = await client.execute(command(), call_ref="one")
        second = await client.execute(command(), call_ref="one")
    assert first == second
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_deadline_cancels_one_slow_attempt():
    async def handler(request):
        await asyncio.sleep(0.12)
        return httpx.Response(200, json=envelope({"record_id": "record"}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=ORIGIN) as http:
        client = StewardHttpClient(
            TrustedTransport(ORIGIN, "token", invocation_id="invoke", deadline_seconds=0.02),
            client=http,
        )
        start = monotonic()
        result = await client.execute(command())
        elapsed = monotonic() - start
    assert result["outcome"] == "ERROR" and elapsed < 0.1, (result, elapsed)


@pytest.mark.asyncio
async def test_response_cap_stops_before_consuming_entire_stream():
    class Body(httpx.AsyncByteStream):
        def __init__(self):
            self.chunks = 0

        async def __aiter__(self):
            for _ in range(12):
                self.chunks += 1
                yield b"x" * (64 * 1024)

    body = Body()

    async def handler(request):
        return httpx.Response(200, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=ORIGIN) as http:
        client = StewardHttpClient(
            TrustedTransport(ORIGIN, "token", invocation_id="invoke"), client=http
        )
        result = await client.execute(command())
    assert result["reason_code"] == "RESPONSE_TOO_LARGE"
    assert body.chunks <= 5, body.chunks


@pytest.mark.asyncio
async def test_cancellation_after_send_records_unknown_attempt():
    class Life(InMemoryRequestLifecycle):
        def __init__(self):
            super().__init__()
            self.finished = []

        async def finish_attempt(self, prepared, result):
            self.finished.append(result)

    life = Life()

    async def handler(request):
        raise asyncio.CancelledError()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=ORIGIN) as http:
        client = StewardHttpClient(
            TrustedTransport(ORIGIN, "token", invocation_id="invoke"), client=http, lifecycle=life
        )
        with pytest.raises(asyncio.CancelledError):
            await client.execute(command())
    assert len(life.finished) == 1


@pytest.mark.asyncio
async def test_ack_failure_becomes_safe_error_without_second_send():
    class Life(InMemoryRequestLifecycle):
        async def finish_attempt(self, prepared, result):
            raise RuntimeError("private backend detail")

    async def handler(request):
        return httpx.Response(200, json=envelope({"record_id": "record"}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=ORIGIN) as http:
        client = StewardHttpClient(
            TrustedTransport(ORIGIN, "token", invocation_id="invoke"), client=http, lifecycle=Life()
        )
        result = await invoke(
            StewardAgentTool("dispatch_vendor", client),
            {"plan_id": "plan", "vendor_id": "vendor", "expected_issue_revision": 2},
        )
    assert result["outcome"] == "ERROR" and "private" not in str(result)


@pytest.mark.asyncio
async def test_body_none_sends_no_bytes_control():
    seen = []

    async def handler(request):
        seen.append(request.content)
        return httpx.Response(200, json=envelope({"record_id": "issue"}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=ORIGIN) as http:
        client = StewardHttpClient(
            TrustedTransport(ORIGIN, "token", invocation_id="invoke"), client=http
        )
        await invoke(
            StewardAgentTool("close_issue", client),
            {"issue_id": "issue", "expected_issue_revision": 1},
        )
    assert seen == [b""]


@pytest.fixture
def real_choice(tmp_path):
    from test_investigation_repair import client_for
    from test_settlement import real_exception

    job, proof, exception, decision = real_exception(tmp_path, chosen=True)
    with client_for(tmp_path) as setup:
        app = setup.app
    return app, job, proof, exception, decision


@pytest.mark.asyncio
async def test_real_rework_wrapper_succeeds_with_actual_operator_invocation(real_choice):
    from test_investigation import ORIGIN as app_origin
    from test_investigation import TOKEN

    app, _job, _proof, _exception, decision = real_choice
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=app_origin
    ) as http:
        client = StewardHttpClient(
            TrustedTransport(app_origin, TOKEN, invocation_id=decision.invocation_id), client=http,
            lifecycle_factory=DurableLifecycle,
        )
        result = await invoke(
            StewardAgentTool("request_rework", client),
            {"decision_id": decision.record_id, "expected_job_revision": 4},
        )
    assert result["outcome"] == "OK", result


@pytest.mark.asyncio
async def test_real_exception_detail_is_not_rejected_as_wrong_dto(real_choice):
    from test_investigation import ORIGIN as app_origin
    from test_investigation import TOKEN

    app, _job, _proof, exception, decision = real_choice
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=app_origin
    ) as http:
        client = StewardHttpClient(
            TrustedTransport(app_origin, TOKEN, invocation_id=decision.invocation_id), client=http,
            lifecycle_factory=DurableLifecycle,
        )
        result = await invoke(
            StewardAgentTool("get_exception", client), {"exception_id": exception}
        )
    assert result["outcome"] == "OK", result


@pytest.mark.asyncio
async def test_generated_mutation_key_always_matches_server_grammar(monkeypatch):
    import re

    import agent.tools.client as module

    monkeypatch.setattr(module.secrets, "token_urlsafe", lambda size: "_possible-leading-symbol")
    prepared = await InMemoryRequestLifecycle().prepare("call", command())
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", prepared.idempotency_key)


@pytest.mark.parametrize(
    "patch",
    [
        {"invocation_id": None},
        {"invocation_id": ""},
        {"timeout_seconds": float("nan")},
        {"deadline_seconds": float("inf")},
    ],
)
def test_invocation_session_config_rejects_unbound_or_nonfinite_limits(patch):

    values = {"origin": ORIGIN, "service_token": "a" * 64, "invocation_id": "invoke"}
    values.update(patch)
    with pytest.raises(ValueError):
        TrustedTransport(**values)


@pytest.mark.asyncio
async def test_malformed_missing_reason_returns_error_instead_of_keyerror():
    async def handler(request):
        value = envelope({"record_id": "record"})
        value.pop("reason_code")
        return httpx.Response(200, json=value)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=ORIGIN) as http:
        client = StewardHttpClient(
            TrustedTransport(ORIGIN, "token", invocation_id="invoke"), client=http
        )
        result = await client.execute(command())
    assert result["outcome"] == "ERROR"


@pytest.mark.asyncio
async def test_denied_busy_reason_is_not_retried():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(403, json=envelope(None, "DENIED", "INSPECTION_IN_PROGRESS"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=ORIGIN) as http:
        client = StewardHttpClient(
            TrustedTransport(ORIGIN, "token", invocation_id="invoke"), client=http
        )
        await client.execute(command())
    assert len(calls) == 1
