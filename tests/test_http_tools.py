"""Stage-B HTTP tool boundary tests; offline_guard must load before imports."""

from __future__ import annotations

import anyio
import httpx
import pytest

from agent.tools.client import Command, StewardHttpClient, TrustedTransport
from agent.tools.session import build_steward_tool_session
from agent.tools.steward import StewardAgentTool


class _Client:
    def __init__(self):
        self.calls = []

    async def execute(self, command, *, call_ref):
        self.calls.append(command)
        return {"outcome": "OK", "reason_code": None, "data": None,
                "unmet": [], "allowed_next": [], "evidence_ids": [], "event_ids": []}


async def _result(tool, raw):
    events = [event async for event in tool.stream({"name": tool.tool_name, "toolUseId": "use-1", "input": raw}, {})]
    return events[-1].tool_result


@pytest.mark.asyncio
async def test_raw_extra_authority_field_is_rejected_before_transport():
    client = _Client()
    tool = StewardAgentTool("find_related_signals", client)

    result = await _result(tool, {"signal_id": "signal-1", "origin": "https://elsewhere.invalid"})

    assert result["status"] == "error"
    assert client.calls == []


@pytest.mark.asyncio
async def test_tool_validates_then_preserves_domain_envelope():
    client = _Client()
    tool = StewardAgentTool("find_related_signals", client)

    result = await _result(tool, {"signal_id": "signal-1"})

    assert result["status"] == "success"
    assert result["content"][0]["json"]["outcome"] == "OK"
    assert client.calls[0].path == "/api/signals/related"
    assert client.calls[0].query == {"signal_id": "signal-1"}


def test_steward_tool_is_an_sdk_agent_tool_with_a_strict_schema():
    tool = StewardAgentTool("find_related_signals", _Client())
    assert tool.tool_type == "function"
    assert tool.tool_spec["inputSchema"]["json"]["additionalProperties"] is False
    assert "origin" not in tool.tool_spec["inputSchema"]["json"]["properties"]


@pytest.mark.asyncio
async def test_hostname_is_blocked_before_anyio_can_resolve_it(monkeypatch):
    async def resolver(*args, **kwargs):
        raise AssertionError("resolver should not run")

    monkeypatch.setattr(anyio, "getaddrinfo", resolver)
    with pytest.raises(AssertionError, match="Offline test blocked"):
        await anyio.connect_tcp("example.invalid", 443)


@pytest.mark.asyncio
async def test_client_keeps_mutation_key_across_transient_retry():
    calls = []

    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(200, json={"outcome": "OK", "reason_code": None, "data": {"record_id": "job-1"},
            "unmet": [], "allowed_next": [], "evidence_ids": [], "event_ids": []}, request=request)

    client = StewardHttpClient(TrustedTransport("http://127.0.0.1:8123", "test-token", invocation_id="invocation-1"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8123"))
    result = await client.execute(Command("dispatch_vendor", "POST", "/api/plans/p1/dispatch",
        body={"vendor_id": "v1"}, expected_revision=2, mutation=True), call_ref="call-1")

    assert result["outcome"] == "OK"
    assert len(calls) == 2
    assert calls[0].headers["idempotency-key"] == calls[1].headers["idempotency-key"]
    assert calls[0].headers["x-steward-expected-revision"] == "2"


@pytest.mark.asyncio
async def test_malformed_success_envelope_is_not_exposed_as_domain_success():
    async def handler(request):
        return httpx.Response(200, json={"outcome": "OK", "reason_code": None, "data": None,
            "unmet": [], "allowed_next": [], "evidence_ids": [], "event_ids": []}, request=request)

    client = StewardHttpClient(TrustedTransport("http://127.0.0.1:8123", "test-token", invocation_id="invocation-1"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8123"))
    result = await client.execute(Command("read_job", "GET", "/api/jobs/j1"))

    assert result["outcome"] == "ERROR"
    assert result["reason_code"] == "MALFORMED_RESPONSE"


@pytest.mark.asyncio
async def test_session_keeps_starter_registry_separate_from_domain_tools():
    session = build_steward_tool_session(TrustedTransport("http://127.0.0.1:8123", "test-token", invocation_id="invocation-1"))
    names = {tool.tool_name for tool in session.tools}
    assert {"find_related_signals", "inspect_completion", "release_payment", "cancel_job"} <= names
    assert {"accept_job", "check_in", "submit_proof", "summarize_workload"}.isdisjoint(names)
    await session.client.aclose()


def test_investigation_tool_descriptions_state_gate_semantics():
    """The model learns hazard/unknown meaning and permitted decision types from the tool contract."""
    from agent.tools.protocol import OPERATIONS, SCHEMA_VERSION

    assert SCHEMA_VERSION == "steward-http-tools-v2"
    classify = OPERATIONS["classify_issue"].description
    assert "hazards" in classify and "unknowns" in classify and "operator review" in classify
    jurisdiction = OPERATIONS["determine_jurisdiction"].description
    assert "unknowns" in jurisdiction
    decide = OPERATIONS["record_investigation_decision"].description
    for name in ("MONITOR", "MARK_ACTIONABLE", "DISPUTE_OFFICIAL_STATUS", "ROUTE_EXTERNAL", "REQUEST_OPERATOR"):
        assert name in decide
    assert "record_operational_decision" in decide
    assert "escalate_to_operator" in decide
    assert "authority" in OPERATIONS["escalate_to_operator"].description
    plan = OPERATIONS["build_resolution_plan"].description
    assert "inspection_unknowns" in plan and "REQUEST_OPERATOR" in plan
    operational = OPERATIONS["record_operational_decision"].description
    for kind in ("dispatch", "settlement", "completion_operator", "authority", "no_vendor", "budget", "rework", "resolve"):
        assert kind in operational
    rework = OPERATIONS["request_rework"].description
    assert "operator's saved decision id" in rework and "get_exception" in rework


def test_build_command_accepts_a_stringified_basis_object():
    """Models sometimes serialize a nested basis as a JSON string; the intent is unambiguous."""
    import json

    from agent.tools.protocol import build_command

    basis = {"kind": "dispatch", "plan_id": "plan-1", "vendor_id": "south_loop_services", "expected_issue_revision": 12}
    values = {"issue_id": "demo-couch", "decision_type": "REQUEST_DISPATCH", "summary": "dispatch the closer vendor",
              "evidence_ids": ["evidence-1"]}
    direct = build_command("record_operational_decision", {**values, "basis": basis})
    stringified = build_command("record_operational_decision", {**values, "basis": json.dumps(basis)})
    assert stringified == direct
    escalation = {"kind": "authority", "issue_id": "demo-couch", "expected_issue_revision": 12,
                  "reason_code": "retained_hazards_require_operator_review"}
    assert build_command("escalate_to_operator", {"basis": json.dumps(escalation)}) == build_command(
        "escalate_to_operator", {"basis": escalation})
    with pytest.raises(ValueError):
        build_command("record_operational_decision", {**values, "basis": "not json"})
    with pytest.raises(ValueError):
        build_command("record_operational_decision", {**values, "basis": json.dumps(["kind", "dispatch"])})


@pytest.mark.asyncio
async def test_agent_tool_accepts_a_stringified_basis_before_transport():
    import json

    client = _Client()
    tool = StewardAgentTool("record_operational_decision", client)
    basis = {"kind": "dispatch", "plan_id": "plan-1", "vendor_id": "south_loop_services", "expected_issue_revision": 11}
    result = await _result(tool, {"issue_id": "demo-couch", "decision_type": "REQUEST_DISPATCH",
        "summary": "dispatch the closer vendor", "evidence_ids": ["evidence-1"], "basis": json.dumps(basis)})
    assert result["status"] == "success"
    assert json.loads(client.calls[0].body_json)["basis"] == basis
    assert client.calls[0].expected_revision == 11
