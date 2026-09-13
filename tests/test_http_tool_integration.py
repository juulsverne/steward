"""Real API and transport controls for the Stage-B consumer boundary."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import socket
import socketserver
import subprocess
import sys
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import ClassVar

import httpx
import jsonschema
import offline_guard
import pytest

from agent import http_contracts as h
from agent.api import OPERATION_IDS as API_OPERATIONS
from agent.http_protocol import OPERATION_IDS
from agent.tools.client import InMemoryRequestLifecycle, TrustedTransport
from agent.tools.protocol import OPERATIONS, ROUTES, Command, build_command, validated_envelope
from agent.tools.session import build_steward_tool_session
from agent.tools.steward import StewardAgentTool

ORIGIN = "http://127.0.0.1:8123"


def result(data=None, *, outcome="OK", reason=None):
    return {
        "outcome": outcome,
        "reason_code": reason,
        "data": data,
        "unmet": [],
        "allowed_next": [],
        "evidence_ids": [],
        "event_ids": [],
    }


async def invoke(session, name, values, ref="call-1"):
    tool = next(tool for tool in session.tools if tool.tool_name == name)
    events = [
        event async for event in tool.stream({"name": name, "toolUseId": ref, "input": values}, {})
    ]
    return events[-1].tool_result["content"][0]["json"]


def test_registry_exact_api_identity_shared_dtos_and_resolvable_sdk_schemas():
    assert OPERATION_IDS is API_OPERATIONS
    assert len(OPERATIONS) == 25
    assert len({op.operation_id for op in ROUTES.values()}) == len(ROUTES)
    receipts = {
        "geocode_location": "record_geocode",
        "search_311": "record_service_lookup",
        "classify_issue": "save_classification",
        "determine_jurisdiction": "save_jurisdiction",
        "record_investigation_decision": "decide",
        "record_operational_decision": "decide_operational",
        "dispatch_vendor": "dispatch",
        "inspect_completion": "inspect",
        "release_payment": "settle",
        "close_issue": "close",
        "cancel_job": "cancel",
        "link_signal_to_issue": "link_signal",
        "escalate_completion_exception": "escalate_to_operator",
        "escalate_issue_exception": "escalate_to_operator",
    }
    for name, receipt in receipts.items():
        assert ROUTES[name].receipt_operation == receipt
    for op in ROUTES.values():
        assert OPERATION_IDS[op.method, op.path] == op.operation_id
        if op.body_model is not None:
            assert issubclass(op.model, op.body_model)
    for name in OPERATIONS:
        schema = StewardAgentTool(name, object()).tool_spec["inputSchema"]["json"]
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False

        def refs(node, definitions):
            if isinstance(node, dict):
                if "$ref" in node:
                    assert node["$ref"].startswith("#/$defs/")
                    assert node["$ref"].split("/")[-1] in definitions
                for value in node.values():
                    refs(value, definitions)
            elif isinstance(node, list):
                for value in node:
                    refs(value, definitions)

        refs(schema, schema.get("$defs", {}))


def test_operational_revision_and_both_escalation_commands_are_exact():
    command = build_command(
        "record_operational_decision",
        {
            "issue_id": "issue",
            "decision_type": "REQUEST_SETTLEMENT",
            "summary": "Inspect recorded proof before payment",
            "evidence_ids": ["evidence"],
            "basis": {
                "kind": "settlement",
                "job_id": "job",
                "submission_id": "proof",
                "verification_id": "verification",
                "expected_job_revision": 4,
            },
        },
    )
    assert command.expected_revision == 4
    assert command.operation_id == "decide_operational"
    assert command.receipt_operation == "decide_operational"
    assert "issue_id" not in command.body
    completion = build_command(
        "escalate_to_operator",
        {
            "basis": {
                "kind": "completion",
                "job_id": "job",
                "submission_id": "proof",
                "verification_id": "verification",
                "denial_event_id": 6,
                "reason_code": "completion_incomplete",
                "expected_job_revision": 4,
            }
        },
    )
    assert completion.path == "/api/jobs/job/exceptions" and completion.expected_revision == 4
    assert set(completion.body) == set(h.CompletionExceptionRequest.model_fields)
    issue = build_command(
        "escalate_to_operator",
        {
            "basis": {
                "kind": "budget",
                "issue_id": "issue",
                "denial_event_id": 8,
                "reason_code": "insufficient_budget",
                "expected_issue_revision": 7,
            }
        },
    )
    assert issue.path == "/api/issues/issue/exceptions" and issue.expected_revision == 7
    assert set(issue.body) == set(h.IssueExceptionRequest.model_fields)


@pytest.mark.parametrize(
    "identifier",
    ["../secret", "https://elsewhere.invalid/", "x?token", "%2f", "/root", "..", "x#fragment"],
)
def test_invalid_domain_paths_cannot_be_constructed(identifier):
    with pytest.raises(ValueError):
        build_command("get_job", {"job_id": identifier})
    with pytest.raises(ValueError):
        Command("get_job", "GET", f"/api/jobs/{identifier}")


@pytest.mark.asyncio
async def test_real_intake_cause_create_link_and_same_key_lost_response_recovery(tmp_path):
    from test_investigation import AT, TOKEN
    from test_investigation import ORIGIN as app_origin
    from test_investigation_repair import client_for, photo

    from agent.store import Store

    with Store(tmp_path / "b4.sqlite3") as store:
        first = photo(store, tmp_path, "first")
        second = photo(store, tmp_path, "second")
        pending = {item.signal_id: item for item in store.pending_invocations()}
        first_inv, second_inv = pending[first.id], pending[second.id]
        assert store.get_event(first_inv.trigger_event_id).issue_id is None
    with client_for(tmp_path) as setup:
        app = setup.app
    sent = []

    class LostResponse(httpx.AsyncBaseTransport):
        def __init__(self):
            self.inner = httpx.ASGITransport(app=app)

        async def handle_async_request(self, request):
            response = await self.inner.handle_async_request(request)
            sent.append(
                (request.headers["Idempotency-Key"], request.headers["X-Steward-Invocation-Id"])
            )
            if len(sent) == 1:
                await response.aclose()
                raise httpx.ReadTimeout("synthetic loss after committed create", request=request)
            return response

        async def aclose(self):
            await self.inner.aclose()

    async with build_steward_tool_session(
        TrustedTransport(app_origin, TOKEN, first_inv.id), http_transport=LostResponse()
    ) as session:
        created = await invoke(
            session,
            "create_issue_from_signal",
            {"signal_id": first.id, "match_rationale": "distinct recorded couch"},
        )
        assert created["outcome"] == "OK", created
        assert sent[0] == sent[1] and len(sent) == 2
        same = await invoke(
            session,
            "create_issue_from_signal",
            {"signal_id": first.id, "match_rationale": "distinct recorded couch"},
        )
        assert same == created and len(sent) == 2
        logical = next(iter(session.client.lifecycle._prepared))
        assert await session.recover(logical) == created and len(sent) == 2
        issue_id = created["data"]["record_id"]
    with Store(tmp_path / "b4.sqlite3") as store:
        issue = store.get_issue_record(issue_id)
        assert store.get_event(first_inv.trigger_event_id).issue_id is None
        assert store.get_invocation(first_inv.id).issue_id == issue_id
        assert store.get_signal(first.id).observed_at == AT
    async with build_steward_tool_session(
        TrustedTransport(app_origin, TOKEN, second_inv.id),
        http_transport=httpx.ASGITransport(app=app),
    ) as session:
        linked = await invoke(
            session,
            "link_signal_to_issue",
            {
                "issue_id": issue_id,
                "signal_id": second.id,
                "match_rationale": "same recorded couch",
                "expected_issue_revision": issue.state_revision,
            },
        )
        assert linked["outcome"] == "OK", linked
        looked_up = await invoke(
            session,
            "search_311",
            {
                "issue_id": issue_id,
                "signal_id": second.id,
                "expected_issue_revision": linked["data"]["state_revision"],
            },
            "lookup",
        )
        assert looked_up["outcome"] == "OK", looked_up
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_invocation(second_inv.id).issue_id == issue_id
        assert len(store.get_issue_record(issue_id).signal_ids) == 2


@pytest.mark.asyncio
async def test_lifecycle_ack_retry_and_permits_preserve_original_identity():
    class Lifecycle(InMemoryRequestLifecycle):
        def __init__(self):
            super().__init__()
            self.ack_count = 0

        async def begin_attempt(self, logical_request_id):
            permit = await super().begin_attempt(logical_request_id)
            return replace(permit, lease_owner="owner", fencing_token=permit.ordinal)

        async def finish_attempt(self, attempt_id, observation):
            self.ack_count += 1
            ack = await super().finish_attempt(attempt_id, observation)
            if self.ack_count == 1:
                raise RuntimeError("synthetic lost acknowledgment")
            return ack

    sent = []

    async def handler(request):
        sent.append(request)
        return httpx.Response(200, json=result({"record_id": "job", "state_revision": 1}))

    lifecycle = Lifecycle()
    async with build_steward_tool_session(
        TrustedTransport(ORIGIN, "token", "invocation"),
        lifecycle=lifecycle,
        http_transport=httpx.MockTransport(handler),
    ) as session:
        command = build_command(
            "dispatch_vendor",
            {"plan_id": "plan", "vendor_id": "vendor", "expected_issue_revision": 1},
        )
        assert (await session.client.execute(command, call_ref="same"))[
            "reason_code"
        ] == "LIFECYCLE_ACK_UNCERTAIN"
        assert len(sent) == 1
        logical = next(iter(lifecycle._prepared))
        assert (await session.recover(logical))["outcome"] == "OK"
        assert len(sent) == 1 and lifecycle.ack_count == 2
        assert sent[0].headers["X-Steward-Invocation-Id"] == "invocation"
        assert sent[0].headers["X-Steward-Lease-Owner"] == "owner"
        assert sent[0].headers["X-Steward-Fencing-Token"] == "1"


@pytest.mark.asyncio
async def test_parallel_same_call_serializes_but_distinct_calls_do_not_collapse():
    sent = []

    async def handler(request):
        sent.append(request.headers["Idempotency-Key"])
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=result({"record_id": "job"}))

    async with build_steward_tool_session(
        TrustedTransport(ORIGIN, "token", "invocation"), http_transport=httpx.MockTransport(handler)
    ) as session:
        cmd = build_command(
            "dispatch_vendor",
            {"plan_id": "plan", "vendor_id": "vendor", "expected_issue_revision": 1},
        )
        left, right = await asyncio.gather(
            session.client.execute(cmd, call_ref="same"),
            session.client.execute(cmd, call_ref="same"),
        )
        assert left == right and len(sent) == 1
        await session.client.execute(cmd, call_ref="different")
        assert len(sent) == 2 and sent[0] != sent[1]


@pytest.fixture
def loopback_server():
    class Handler(BaseHTTPRequestHandler):
        mode = "ok"
        calls: ClassVar[list] = []

        def do_GET(self):
            type(self).calls.append(dict(self.headers))
            if self.mode == "timeout":
                Event().wait(0.2)
            if self.headers.get("Authorization") != "Bearer token":
                status, payload = 401, result(outcome="ERROR", reason="AUTH_REQUIRED")
            elif self.mode == "denied":
                status, payload = 403, result(outcome="DENIED", reason="NOT_ALLOWED")
            else:
                status, payload = (
                    200,
                    result(
                        {
                            "budget_id": "budget",
                            "initial_cents": 50000,
                            "reserved_cents": 7200,
                            "spent_cents": 0,
                            "available_cents": 42800,
                        }
                    ),
                )
            body = b"broken-json" if self.mode == "malformed" else json.dumps(payload).encode()
            if self.mode == "oversize":
                body = b"x" * (300 * 1024)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # The timeout/size tests deliberately close before consuming the body.

        def log_message(self, *args):
            pass

    class LiteralServer(ThreadingHTTPServer):
        def server_bind(self):
            # HTTPServer's default getfqdn performs an unnecessary reverse lookup.
            socketserver.TCPServer.server_bind(self)
            self.server_name = "127.0.0.1"
            self.server_port = self.server_address[1]

    server = LiteralServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.asyncio
async def test_actual_allocated_loopback_success_denial_auth_and_malformed(loopback_server):
    import boto3
    import strands

    port, handler = loopback_server
    origin = f"http://127.0.0.1:{port}"
    assert offline_guard._allowed_loopback is None
    with offline_guard.allow_literal_loopback(port):
        assert boto3.Session is offline_guard.blocked and strands.Agent is offline_guard.blocked
        for mode, token, expected in [
            ("ok", "token", "OK"),
            ("denied", "token", "DENIED"),
            ("ok", "wrong", "ERROR"),
            ("malformed", "token", "ERROR"),
        ]:
            handler.mode = mode
            async with build_steward_tool_session(
                TrustedTransport(origin, token, "invocation")
            ) as session:
                response = await invoke(session, "get_budget", {})
                assert response["outcome"] == expected, response
                assert session.client._client.trust_env is False
                assert session.client._client.follow_redirects is False
                assert all(tool.tool_name != "request_recovery" for tool in session.tools)
            assert session.client._client.is_closed
        assert all(headers["X-Steward-Invocation-Id"] == "invocation" for headers in handler.calls)
        assert len(handler.calls) == 4
    assert offline_guard._allowed_loopback is None


@pytest.mark.asyncio
async def test_actual_loopback_timeout_and_response_size_are_bounded(loopback_server):
    port, handler = loopback_server
    origin = f"http://127.0.0.1:{port}"
    with offline_guard.allow_literal_loopback(port):
        handler.mode = "oversize"
        async with build_steward_tool_session(
            TrustedTransport(origin, "token", "invocation")
        ) as session:
            assert (await invoke(session, "get_budget", {}))["reason_code"] == "RESPONSE_TOO_LARGE"
        handler.mode = "timeout"
        async with build_steward_tool_session(
            TrustedTransport(origin, "token", "invocation", timeout_seconds=0.02)
        ) as session:
            assert (await invoke(session, "get_budget", {}))["reason_code"] == "TRANSPORT_UNCERTAIN"
        assert (
            len(handler.calls) == 4
        )  # one oversize response plus three bounded uncertain requests


@pytest.mark.asyncio
async def test_command_copy_and_changed_call_ref_cannot_change_original_request():
    sent = []

    async def handler(request):
        sent.append(request)
        return httpx.Response(200, json=result({"record_id": "job"}))

    async with build_steward_tool_session(
        TrustedTransport(ORIGIN, "token", "invocation"), http_transport=httpx.MockTransport(handler)
    ) as session:
        first = build_command(
            "dispatch_vendor",
            {"plan_id": "plan", "vendor_id": "vendor", "expected_issue_revision": 1},
        )
        first.body["vendor_id"] = "changed-copy"
        assert first.body["vendor_id"] == "vendor"
        await session.client.execute(first, call_ref="same")
        changed = build_command(
            "dispatch_vendor",
            {"plan_id": "plan", "vendor_id": "other", "expected_issue_revision": 1},
        )
        assert (await session.client.execute(changed, call_ref="same"))[
            "reason_code"
        ] == "LOGICAL_REQUEST_CONFLICT"
        assert len(sent) == 1


@pytest.mark.parametrize("token", ["", "contains space", "token\r\nInjected:yes"])
def test_missing_or_invalid_credential_is_rejected_before_client(token):
    with pytest.raises(ValueError):
        TrustedTransport(ORIGIN, token, "invocation")


@pytest.mark.asyncio
async def test_guard_rejects_wrong_port_dns_and_supplied_socket_before_native_work(
    monkeypatch, loopback_server
):
    port, _ = loopback_server
    observed = []

    async def async_spy(*args, **kwargs):
        observed.append((args, kwargs))

    def sync_spy(*args, **kwargs):
        observed.append((args, kwargs))

    monkeypatch.setattr(offline_guard, "_loop_create_connection", async_spy)
    monkeypatch.setattr(offline_guard, "_getaddrinfo", sync_spy)
    with offline_guard.allow_literal_loopback(port):
        for host, target in [
            ("localhost", port),
            ("example.invalid", port),
            ("127.0.0.1", port + 1),
            ("0.0.0.0", port),
        ]:
            with pytest.raises(AssertionError, match="Offline test blocked"):
                socket.getaddrinfo(host, target)
            with pytest.raises(AssertionError, match="Offline test blocked"):
                await offline_guard.guarded_create_connection(object(), lambda: None, host, target)
        with pytest.raises(AssertionError, match="Offline test blocked"):
            await offline_guard.guarded_create_connection(
                object(), lambda: None, "127.0.0.1", port, sock=object()
            )
        if sys.platform == "win32":
            monkeypatch.setattr(offline_guard, "_proactor_connect", sync_spy)
            monkeypatch.setattr(offline_guard, "_sock_connect", async_spy)
            with pytest.raises(AssertionError, match="Offline test blocked"):
                offline_guard.guarded_proactor_connect(
                    object(), object(), ("example.invalid", port)
                )
            with pytest.raises(AssertionError, match="Offline test blocked"):
                await offline_guard.guarded_sock_connect(
                    object(), object(), ("127.0.0.1", port + 1)
                )
    assert observed == []


def test_default_guard_precedes_sdk_imports_in_fresh_process(tmp_path):
    probe = tmp_path / "test_guard_probe.py"
    probe.write_text(
        'import sys\nassert "offline_guard" in sys.modules\nimport offline_guard\n'
        "import boto3\nimport strands\ndef test_guard():\n"
        "    assert boto3.Session is offline_guard.blocked\n"
        "    assert strands.Agent is offline_guard.blocked\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", "pyproject.toml", str(probe), "-q"],
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert run.returncode == 0, (run.returncode, run.stdout, run.stderr)
    assert "1 passed" in run.stdout


def test_client_modules_have_no_api_store_or_web_runtime_import():
    # Source check complements the separate actual imports exercised throughout this file.
    for path in Path("src/agent/tools").glob("*.py"):
        if path.name not in {
            "client.py",
            "protocol.py",
            "lifecycle.py",
            "session.py",
            "steward.py",
        }:
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(
            r"^(?:from|import)\s+(?:.*\.)?(?:api|store|operations|fastapi)\b", text, re.MULTILINE
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["prepare", "permit", "invalid_key", "foreign_invocation"])
async def test_failed_lifecycle_never_sends_or_exposes_private_error(stage):
    sent = []

    class Lifecycle(InMemoryRequestLifecycle):
        async def prepare(self, call_ref, command):
            if stage == "prepare":
                raise RuntimeError("secret backend path")
            prepared = await super().prepare(call_ref, command)
            if stage == "invalid_key":
                return replace(prepared, idempotency_key="_invalid")
            if stage == "foreign_invocation":
                return replace(prepared, invocation_id="another-invocation")
            return prepared

        async def begin_attempt(self, logical_request_id):
            raise RuntimeError("secret permit backend")

    async def handler(request):
        sent.append(request)
        return httpx.Response(200, json=result({"record_id": "job"}))

    async with build_steward_tool_session(
        TrustedTransport(ORIGIN, "token", "invocation"),
        lifecycle=Lifecycle(),
        http_transport=httpx.MockTransport(handler),
    ) as session:
        response = await invoke(
            session,
            "dispatch_vendor",
            {"plan_id": "plan", "vendor_id": "vendor", "expected_issue_revision": 1},
        )
        assert response["outcome"] == "ERROR" and "secret" not in str(response)
        assert sent == []


@pytest.mark.asyncio
async def test_same_client_factory_and_independent_sessions_close_cleanly():
    clients = []
    observed = []

    def factory(client):
        clients.append(client)
        return InMemoryRequestLifecycle()

    async def handler(request):
        observed.append(
            (request.headers["Authorization"], request.headers["X-Steward-Invocation-Id"])
        )
        return httpx.Response(
            200,
            json=result(
                {
                    "budget_id": "budget",
                    "initial_cents": 50000,
                    "reserved_cents": 0,
                    "spent_cents": 0,
                    "available_cents": 50000,
                }
            ),
        )

    first = build_steward_tool_session(
        TrustedTransport(ORIGIN, "first-token", "first-invocation"),
        lifecycle_factory=factory,
        http_transport=httpx.MockTransport(handler),
    )
    second = build_steward_tool_session(
        TrustedTransport(ORIGIN, "second-token", "second-invocation"),
        lifecycle_factory=factory,
        http_transport=httpx.MockTransport(handler),
    )
    async with first, second:
        assert clients == [first.client, second.client]
        assert first.client._client is not second.client._client
        await asyncio.gather(invoke(first, "get_budget", {}), invoke(second, "get_budget", {}))
        assert set(observed) == {
            ("Bearer first-token", "first-invocation"),
            ("Bearer second-token", "second-invocation"),
        }
        assert "first-token" not in repr(first.client.transport)
    assert first.client._client.is_closed and second.client._client.is_closed
    assert (await invoke(first, "get_budget", {}))["reason_code"] == "SESSION_CLOSED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,outcome,reason,expected",
    [
        (503, "ERROR", "INSPECTION_IN_PROGRESS", 3),
        (503, "ERROR", "INSPECTION_INTERRUPTED", 1),
        (403, "DENIED", "INSPECTION_IN_PROGRESS", 1),
        (200, "NEEDS_REVIEW", "INSPECTION_IN_PROGRESS", 1),
        (503, "ERROR", "TRANSPORT_UNCERTAIN", 1),
    ],
)
async def test_only_actual_live_inspection_busy_retries(status, outcome, reason, expected):
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(status, json=result(outcome=outcome, reason=reason))

    async with build_steward_tool_session(
        TrustedTransport(ORIGIN, "token", "invocation"), http_transport=httpx.MockTransport(handler)
    ) as session:
        args = {"job_id": "job", "submission_id": "proof", "expected_job_revision": 3}
        await invoke(session, "inspect_completion", args)
        await invoke(session, "inspect_completion", args)
        assert len(requests) == expected
        assert len({request.headers["Idempotency-Key"] for request in requests}) == 1
        assert len({request.headers["X-Steward-Attempt-Id"] for request in requests}) == expected


@pytest.mark.asyncio
async def test_invalid_raw_nested_ids_collections_and_nonfinite_values_never_prepare():
    class Spy:
        def __init__(self):
            self.calls = []

        async def execute(self, command, *, call_ref):
            self.calls.append(command)
            return result({"record_id": "unexpected"})

    spy = Spy()
    tool = StewardAgentTool("classify_issue", spy)
    base = {
        "issue_id": "issue",
        "signal_id": "signal",
        "category": "bulky_waste",
        "expected_issue_revision": 1,
    }
    for patch in [
        {"expected_issue_revision": True},
        {"large_object_count": float("nan")},
        {"visible_objects": ["couch"] * 65},
        {"full_cleanup_scope": "x" * 2001},
        {"supporting_evidence_ids": ["../other"]},
        {"lease_owner": "forged"},
    ]:
        events = [
            event
            async for event in tool.stream(
                {"name": tool.tool_name, "toolUseId": "tool-use", "input": base | patch}, {}
            )
        ]
        assert events[-1].tool_result["status"] == "error"
    assert spy.calls == []


@pytest.mark.asyncio
async def test_redirect_never_follows_or_retries_with_credentials():
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://elsewhere.invalid/private"})

    async with build_steward_tool_session(
        TrustedTransport(ORIGIN, "token", "invocation"), http_transport=httpx.MockTransport(handler)
    ) as session:
        response = await invoke(session, "get_budget", {})
        assert response["reason_code"] == "UNTRUSTED_REDIRECT" and len(requests) == 1
        assert str(requests[0].url).startswith(ORIGIN + "/")


@pytest.mark.asyncio
async def test_real_proof_invocation_inspection_denial_and_escalation_use_one_session(tmp_path):
    from test_inspection import proof_ready_job, valid_findings
    from test_investigation import ORIGIN as app_origin
    from test_investigation import TOKEN
    from test_investigation_repair import client_for

    from agent.store import Store

    job, proof = proof_ready_job(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        invocation = next(inv for inv in store.pending_invocations() if inv.job_id == job)

    def partial(*_):
        finding = valid_findings()
        finding["findings"]["area_clear"] = False
        return finding

    with client_for(tmp_path, completion_inspector=partial) as setup:
        app = setup.app
    async with build_steward_tool_session(
        TrustedTransport(app_origin, TOKEN, invocation.id),
        http_transport=httpx.ASGITransport(app=app),
    ) as session:
        inspected = await invoke(
            session,
            "inspect_completion",
            {"job_id": job, "submission_id": proof, "expected_job_revision": 3},
            "inspect",
        )
        assert inspected["outcome"] == "OK" and inspected["data"]["total"] == 90, inspected
        revision = inspected["data"]["state_revision"]
        denied = await invoke(
            session,
            "release_payment",
            {"job_id": job, "submission_id": proof, "expected_job_revision": revision},
            "settle",
        )
        assert denied["outcome"] == "DENIED" and denied["event_ids"], denied
        escalated = await invoke(
            session,
            "escalate_to_operator",
            {
                "basis": {
                    "kind": "completion",
                    "job_id": job,
                    "submission_id": proof,
                    "verification_id": inspected["data"]["verification_id"],
                    "denial_event_id": denied["event_ids"][0],
                    "reason_code": "completion_incomplete",
                    "expected_job_revision": revision,
                }
            },
            "escalate",
        )
        assert escalated["outcome"] == "NEEDS_REVIEW", escalated
        details = await invoke(
            session,
            "get_exception",
            {"exception_id": escalated["data"]["record_id"]},
            "read-exception",
        )
        assert details["outcome"] == "OK", details
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.payment_for_job(job) is None
        assert store.open_completion_exception(job) is not None


def test_real_inspection_success_requires_score_and_input_result_revisions(tmp_path):
    from test_inspection import proof_ready_job, valid_findings
    from test_investigation_repair import client_for, headers

    job, proof = proof_ready_job(tmp_path)
    with client_for(tmp_path, completion_inspector=lambda *_: valid_findings()) as client:
        response = client.post(
            f"/api/jobs/{job}/inspect",
            headers=headers("inspect", 3),
            json={"submission_id": proof},
        )
        assert response.status_code == 200, response.text
    actual = response.json()
    assert validated_envelope(actual, "inspect_completion") == actual
    for field in ("total", "input_job_revision", "state_revision"):
        for absent in (False, True):
            malformed = copy.deepcopy(actual)
            if absent:
                malformed["data"].pop(field)
            else:
                malformed["data"][field] = None
            assert validated_envelope(malformed, "inspect_completion")["reason_code"] == (
                "MALFORMED_RESPONSE"
            ), (field, absent)
    # No-result errors retain deliberate nulls rather than inventing a verification.
    failed = copy.deepcopy(actual)
    failed.update(outcome="ERROR", reason_code="INSPECTOR_ERROR")
    for field in (
        "total",
        "input_job_revision",
        "state_revision",
        "verification_id",
        "findings",
        "checks",
        "components",
    ):
        failed["data"][field] = None
    assert validated_envelope(failed, "inspect_completion", 503) == failed


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "timeout", "error"])
async def test_known_terminal_disposition_survives_response_cleanup(failure):
    calls = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * (300 * 1024)

        async def aclose(self):
            if failure == "cancel":
                raise asyncio.CancelledError()
            if failure == "timeout":
                raise httpx.ReadTimeout("cleanup failed after terminal disposition")
            raise RuntimeError("private cleanup detail")

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=Body(), headers={"X-Request-ID": "oversized-request"})

    async with build_steward_tool_session(
        TrustedTransport(ORIGIN, "token", "invocation"),
        http_transport=httpx.MockTransport(handler),
    ) as session:
        command = build_command(
            "dispatch_vendor",
            {"plan_id": "plan", "vendor_id": "vendor", "expected_issue_revision": 1},
        )
        if failure == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await session.client.execute(command, call_ref="same")
        else:
            output = await session.client.execute(command, call_ref="same")
            assert output["reason_code"] == "RESPONSE_TOO_LARGE"
        observations = list(session.client.lifecycle._observations.values())
        assert len(observations) == 1
        observation = observations[0]
        assert observation.status_code == 200 and observation.request_id == "oversized-request"
        assert observation.result["reason_code"] == "RESPONSE_TOO_LARGE"
        assert not observation.retryable
        assert observation.cancelled == (failure == "cancel")
        assert await session.recover(observation.logical_request_id) == observation.result
        assert await session.client.execute(command, call_ref="same") == observation.result
        assert len(calls) == 1
