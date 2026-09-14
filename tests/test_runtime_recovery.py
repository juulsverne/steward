"""Real HTTP effects, response loss, takeover and authentic paid-history recovery."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from test_api_auth import ORIGIN, SIGNING, TOKEN
from test_runtime import seeded

from agent.api import create_app
from agent.config import ApiSettings
from agent.core import ExecutionRequest
from agent.runtime_contracts import LogicalRequest
from agent.store import Store
from agent.tools.client import TrustedTransport
from agent.tools.durable import DurableLifecycle
from agent.tools.protocol import build_command
from agent.tools.session import build_steward_tool_session


def app_for(path, clock, **kwargs):
    return create_app(ApiSettings(store_path=path, origin=ORIGIN, local_http=True,
        session_secret=SIGNING, service_token=TOKEN, image_root=path.parent / "images"),
        runtime_clock=lambda: clock[0], **kwargs)


async def prepare_tool(life, command, ordinal=1):
    if ordinal == 1:
        await life.authorize(ExecutionRequest("model", 1, life.claim.invocation_id))
    await life.authorize(ExecutionRequest("tool", ordinal, life.claim.invocation_id, command=command))
    return await life.prepare("untrusted-provider-id", command)


def wire_headers(life, prepared, attempt):
    return {"Authorization": f"Bearer {TOKEN}", "X-Steward-Invocation-Id": life.claim.invocation_id,
        "X-Steward-Lease-Owner": attempt.lease_owner, "X-Steward-Fencing-Token": str(attempt.fencing_token),
        "X-Steward-Attempt-Id": attempt.attempt_id, "Idempotency-Key": prepared.idempotency_key,
        "X-Steward-Expected-Revision": str(prepared.command.expected_revision), "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_actual_command_tampering_and_stale_receipt_replay_are_fenced(tmp_path):
    path, invocation = seeded(tmp_path)
    clock = [datetime.now(UTC)]
    app = app_for(path, clock)
    with Store(path) as store:
        inv = store.get_invocation(invocation)
        revision = store.get_issue_record(inv.issue_id).state_revision
    command = build_command("geocode_location", {"issue_id": inv.issue_id, "signal_id": inv.signal_id,
                                                  "expected_issue_revision": revision})
    async with build_steward_tool_session(TrustedTransport(ORIGIN, TOKEN, invocation),
            lifecycle_factory=DurableLifecycle, http_transport=httpx.ASGITransport(app)) as session:
        life = session.client.lifecycle
        await life.acquire()
        prepared = await prepare_tool(life, command)
        permit = await life.begin_attempt(prepared.logical_request_id)
        headers = wire_headers(life, prepared, permit)
        raw = session.client._client
        wrong = await raw.post(command.path, headers=headers, json={"signal_id": "other-signal"})
        assert wrong.status_code in {403, 404, 409, 422}, wrong.json()
        with Store(path) as store:
            assert store.get_issue_record(inv.issue_id).state_revision == revision
        good = await raw.post(command.path, headers=headers, content=command.body_json)
        assert good.status_code == 200, good.json()
        result = good.json()
        clock[0] += timedelta(seconds=35)
        async with build_steward_tool_session(TrustedTransport(ORIGIN, TOKEN, invocation),
                lifecycle_factory=DurableLifecycle, http_transport=httpx.ASGITransport(app)) as fresh:
            await fresh.client.lifecycle.acquire()
            old = await raw.post(command.path, headers=headers, content=command.body_json)
            assert old.status_code in {403, 409, 422}, old.json()
            recovered = await fresh.client.lifecycle.control("reconcile", logical_request_id=prepared.logical_request_id)
            assert json.loads(recovered["terminal_json"]) == result
            assert recovered["idempotency_key"] == prepared.idempotency_key
        with Store(path) as store:
            assert store.get_issue_record(inv.issue_id).state_revision == result["data"]["state_revision"]
            assert store.db.execute("SELECT COUNT(*) FROM request_receipts WHERE idempotency_key=?",
                                    (prepared.idempotency_key,)).fetchone()[0] == 1
            saved_receipt = store.db.execute("SELECT id FROM request_receipts WHERE idempotency_key=?",
                                             (prepared.idempotency_key,)).fetchone()[0]
            assert store.get_request(saved_receipt).invocation_id == invocation
            # This unchanged seeded geocode reuses its historical event; do not backfill it.


class ProcessCrash(BaseException):
    """Simulate process loss without reporting a normal SDK/transport failure."""


@pytest.mark.asyncio
async def test_paid_before_resolve_long_offline_model_recovers_once(tmp_path, monkeypatch):
    from strands.agent.agent import Agent as OfflineAgent
    from test_agent_contract import scripted_model
    from test_settlement import inspected_job

    from agent import core
    from agent.runtime import run_invocation
    job_id, proof_id = inspected_job(tmp_path)
    path = tmp_path / "b4.sqlite3"
    with Store(path) as store:
        invocation = store.invocation_for_event(store.proof_event_for_submission(proof_id).id).id
    clock = [datetime.now(UTC)]
    app = app_for(path, clock)
    sent = []
    class CrashAfterCommit(httpx.ASGITransport):
        async def handle_async_request(self, request):
            response = await super().handle_async_request(request)
            if request.url.path.endswith("/settle"):
                sent.append(request.headers["Idempotency-Key"])
                assert response.status_code == 200
                raise ProcessCrash()
            return response
    monkeypatch.setattr(core, "Agent", OfflineAgent)
    with pytest.raises(ProcessCrash):
        await run_invocation(TrustedTransport(ORIGIN, TOKEN, invocation),
            model=scripted_model(lambda *_: [("release_payment", {"job_id": job_id, "submission_id": proof_id,
                                                               "expected_job_revision": 4})]),
            http_transport=CrashAfterCommit(app))
    with Store(path) as store:
        assert store.payment_for_job(job_id) is not None
        assert store.get_issue_record("issue").status == "RESOLUTION_ACTIVE"
        assert store.get_invocation(invocation).status == "RUNNING"
        unresolved = [LogicalRequest.model_validate_json(row[0]) for row in store.db.execute("SELECT record_json FROM runtime_requests")
                      if LogicalRequest.model_validate_json(row[0]).terminal_json is None]
        assert len(unresolved) == 1 and unresolved[0].command.operation == "release_payment"
    clock[0] += timedelta(minutes=5)
    def recover(cycle, messages, prompt):
        case = json.loads(prompt.split("<untrusted_case_json>\n")[1].split("\n</untrusted_case_json>")[0])
        if cycle == 1:
            payment = case["payments"][0]
            return [("record_operational_decision", {"issue_id": "issue", "decision_type": "RESOLVE",
                "summary": "The exact accepted proof has already been paid; close the case.",
                "basis": {"kind": "resolve", "job_id": job_id, "payment_id": payment["id"],
                          "submission_id": proof_id, "verification_id": payment["verification_id"],
                          "expected_issue_revision": case["issue"]["state_revision"]}})]
        assert cycle == 2
        return [("close_issue", {"issue_id": "issue", "expected_issue_revision": case["issue"]["state_revision"]})]
    outcome = await run_invocation(TrustedTransport(ORIGIN, TOKEN, invocation), model=scripted_model(recover),
                                   http_transport=httpx.ASGITransport(app))
    assert outcome.saved_stop == "RESOLVED", outcome
    with Store(path) as store:
        assert store.db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1
        assert store.get_issue_record("issue").status == "RESOLVED"
        assert store.get_invocation(invocation).status == "COMPLETED"
        assert store.db.execute("SELECT episode,model_cycles FROM runtime_state WHERE invocation_id=?", (invocation,)).fetchone()[:] == (2, 3)
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_takeover_during_real_completion_keeps_observation_without_effect(tmp_path):
    from test_inspection import proof_ready_job, valid_findings

    from agent.coordinator import Coordinator
    job_id, proof_id = proof_ready_job(tmp_path)
    path = tmp_path / "b4.sqlite3"
    with Store(path) as store:
        invocation = store.invocation_for_event(store.proof_event_for_submission(proof_id).id).id
    clock = [datetime.now(UTC)]
    taken = []
    def inspector(*_):
        clock[0] += timedelta(seconds=35)
        # A different writer succeeds here: the provider is outside the SQLite transaction.
        with Store(path) as store:
            taken.append(Coordinator(store, clock=lambda: clock[0]).claim(invocation, "replacement", "takeover"))
        return valid_findings()
    app = app_for(path, clock, completion_inspector=inspector)
    async with build_steward_tool_session(TrustedTransport(ORIGIN, TOKEN, invocation),
            lifecycle_factory=DurableLifecycle, http_transport=httpx.ASGITransport(app)) as session:
        life = session.client.lifecycle
        await life.acquire()
        command = build_command("inspect_completion", {"job_id": job_id, "submission_id": proof_id, "expected_job_revision": 3})
        prepared = await prepare_tool(life, command)
        attempt = await life.begin_attempt(prepared.logical_request_id)
        response = await session.client._client.post(command.path, headers=wire_headers(life, prepared, attempt), content=command.body_json)
        assert response.status_code in {409, 422}, response.text
    assert len(taken) == 1
    with Store(path) as store:
        assert store.get_job(job_id).state_revision == 3
        assert store.get_job(job_id).current_verification_id is None
        assert store.db.execute("SELECT COUNT(*) FROM completion_inspection_observations").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM request_receipts WHERE idempotency_key=?", (prepared.idempotency_key,)).fetchone()[0] == 0


def test_startup_discovers_saved_pending_and_never_constructs_default_provider(tmp_path):
    from threading import Event

    from fastapi.testclient import TestClient

    from agent.coordinator import Coordinator
    path, invocation = seeded(tmp_path)
    called = Event()
    async def runner(transport, **kwargs):
        assert transport.invocation_id == invocation
        # This injected runner is only the dispatcher scheduling control; real execution is tested above.
        with Store(path) as store:
            co = Coordinator(store)
            claim = co.claim(invocation, "startup-test", "startup")
            co.complete(claim, "ERROR", "INJECTED_STOP")
        called.set()
    app = create_app(ApiSettings(store_path=path, origin=ORIGIN, local_http=True,
        session_secret=SIGNING, service_token=TOKEN, runtime_enabled=True), runtime_runner=runner)
    with TestClient(app, base_url=ORIGIN):
        assert called.wait(5)
    with Store(path) as store:
        assert store.get_invocation(invocation).status == "ERROR"


@pytest.mark.asyncio
async def test_private_controls_require_service_and_public_trace_is_safe_and_paginated(tmp_path, monkeypatch):
    from agent.coordinator import Coordinator
    from agent.runtime_api import status_projection
    path, invocation = seeded(tmp_path)
    with Store(path) as store:
        co = Coordinator(store)
        claim = co.claim(invocation, "private-owner", "private-nonce")
        for i in range(23):
            co.execution(claim, f"ctx-{i}", "context", i)
        first = status_projection(store, invocation)
        second = status_projection(store, invocation, after_id=first.next_cursor)
        assert len(first.trace) == 20 and len(second.trace) == 3
        assert first.truncated and not second.truncated
        assert not {item.id for item in first.trace} & {item.id for item in second.trace}
        raw = first.model_dump_json()
        for private in ("private-owner", "private-nonce", "idempotency_key", "fencing_token", TOKEN):
            assert private not in raw
    app = app_for(path, [datetime.now(UTC)])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=ORIGIN) as client:
        response = await client.post(f"/internal/invocations/{invocation}/claim", json={"nonce": "x", "owner": "evil"})
        assert response.status_code == 401
        response = await client.get(f"/api/invocations/{invocation}", headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200, response.text


def test_actual_startup_dispatcher_runs_real_http_agent_and_resume_stays_dormant(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient
    from strands.agent.agent import Agent as OfflineAgent
    from test_agent_contract import scripted_model

    from agent import core
    path, invocation = seeded(tmp_path)
    cycles = []
    def script(cycle, messages, prompt):
        cycles.append(cycle)
        case = json.loads(prompt.split("<untrusted_case_json>\n")[1].split("\n</untrusted_case_json>")[0])
        if cycle == 1:
            return [("record_investigation_decision", {"issue_id": "demo-couch", "decision_type": "MONITOR",
                "expected_issue_revision": case["issue"]["state_revision"], "summary": "Await independent evidence."})]
        prior = next(b["toolResult"] for m in reversed(messages) for b in m["content"] if "toolResult" in b)
        return [("apply_investigation_decision", {"issue_id": "demo-couch", "decision_id": prior["content"][0]["json"]["data"]["record_id"],
                 "expected_issue_revision": case["issue"]["state_revision"]})]
    monkeypatch.setattr(core, "Agent", OfflineAgent)
    app = create_app(ApiSettings(store_path=path, origin=ORIGIN, local_http=True, session_secret=SIGNING,
        service_token=TOKEN, runtime_enabled=True), runtime_model_factory=lambda: scripted_model(script),
        runtime_http_transport=lambda app: httpx.ASGITransport(app))
    with TestClient(app, base_url=ORIGIN) as client:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = client.get(f"/api/invocations/{invocation}", headers={"Authorization": f"Bearer {TOKEN}"})
            assert response.status_code == 200, response.text
            if response.json()["data"]["status"] == "WAITING":
                break
            time.sleep(.05)
        assert response.json()["data"]["status"] == "WAITING", response.json()
        assert client.post(f"/api/invocations/{invocation}/resume", headers={"Authorization": f"Bearer {TOKEN}"}).json()["reason_code"] == "PROCESSING_ENABLED"
    assert cycles == [1, 2]
