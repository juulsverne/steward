"""Coordinator ACK loss must stop new work without stranding committed domain effects."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from test_agent_contract import scripted_model
from test_api_auth import ORIGIN, TOKEN
from test_runtime import seeded
from test_runtime_recovery import app_for

from agent import core
from agent.runtime import run_invocation
from agent.runtime_contracts import LogicalRequest
from agent.store import Store
from agent.tools.client import TrustedTransport


@pytest.mark.asyncio
@pytest.mark.parametrize("loss", ["finish-before-commit", "finish-after-commit", "observe-after-commit"])
async def test_ack_loss_preserves_original_request_and_fenced_recovery(tmp_path, monkeypatch, loss):
    from strands.agent.agent import Agent as OfflineAgent
    monkeypatch.setattr(core, "Agent", OfflineAgent)
    path, invocation = seeded(tmp_path)
    clock = [datetime.now(UTC)]
    app = app_for(path, clock)
    class LostAck(httpx.ASGITransport):
        dropped = 0
        decisions = 0
        async def handle_async_request(self, request):
            body = json.loads(request.content) if request.content else {}
            target = False
            if loss.startswith("finish") and request.url.path.endswith("/finish"):
                target = bool(json.loads(json.loads(body["observation_json"])["result_json"]).get("event_ids"))
            elif loss.startswith("observe") and request.url.path.endswith("/observe"):
                target = body.get("kind") == "tool"
            if target:
                self.dropped += 1
                if loss.endswith("after-commit"):
                    response = await super().handle_async_request(request)
                    assert response.status_code == 200
                    await response.aclose()
                raise httpx.ReadError("injected control acknowledgment loss", request=request)
            if request.url.path.endswith("/decisions"):
                self.decisions += 1
            return await super().handle_async_request(request)
    def decide(cycle, _messages, prompt):
        assert cycle == 1, "No model advancement after missing control acknowledgment"
        case = json.loads(prompt.split("<untrusted_case_json>\n")[1].split("\n</untrusted_case_json>")[0])
        return [("record_investigation_decision", {"issue_id": "demo-couch", "decision_type": "MONITOR",
            "expected_issue_revision": case["issue"]["state_revision"], "summary": "Await independent evidence."})]
    transport = LostAck(app)
    result = await run_invocation(TrustedTransport(ORIGIN, TOKEN, invocation), model=scripted_model(decide), http_transport=transport)
    with Store(path) as store:
        original = store.get_invocation(invocation)
        assert original.status == "RUNNING", result
        assert result.interruption is not None
        assert transport.dropped == 3 and transport.decisions == 1
        receipts = store.db.execute("SELECT id FROM request_receipts WHERE operation='decide'").fetchall()
        assert len(receipts) == 1
        saved = next(LogicalRequest.model_validate_json(row[0]) for row in store.db.execute("SELECT record_json FROM runtime_requests")
                     if LogicalRequest.model_validate_json(row[0]).command.operation == "record_investigation_decision")
    clock[0] += timedelta(seconds=35)
    def apply(cycle, _messages, prompt):
        assert cycle == 1
        with Store(path) as store:
            recovered = LogicalRequest.model_validate_json(store.db.execute("SELECT record_json FROM runtime_requests WHERE id=?", (saved.id,)).fetchone()[0])
            assert recovered.terminal_json is not None, "Reconcile before any fresh model choice"
            assert recovered.idempotency_key == saved.idempotency_key and recovered.deadline == saved.deadline
        case = json.loads(prompt.split("<untrusted_case_json>\n")[1].split("\n</untrusted_case_json>")[0])
        event = next(item for item in case["events"] if item["event_type"] == "INVESTIGATION_DECIDED")
        return [("apply_investigation_decision", {"issue_id": "demo-couch", "decision_id": event["record_id"],
            "expected_issue_revision": case["issue"]["state_revision"]})]
    recovered = await run_invocation(TrustedTransport(ORIGIN, TOKEN, invocation), model=scripted_model(apply), http_transport=httpx.ASGITransport(app))
    assert recovered.saved_stop == "INVESTIGATION_ACTION_APPLIED"
    assert recovered.interruption is None
    with Store(path) as store:
        current = store.get_invocation(invocation)
        assert current.status == "WAITING" and current.fencing_token > original.fencing_token
        assert store.db.execute("SELECT id FROM request_receipts WHERE operation='decide'").fetchall() == receipts
        assert store.db.execute("SELECT COUNT(*) FROM runtime_attempts WHERE request_id=?", (saved.id,)).fetchone()[0] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("uses", [[], [("get_budget", {"unexpected": "invalid"})]])
async def test_observed_model_end_or_invalid_input_remains_terminal(tmp_path, monkeypatch, uses):
    from strands.agent.agent import Agent as OfflineAgent
    monkeypatch.setattr(core, "Agent", OfflineAgent)
    path, invocation = seeded(tmp_path)
    result = await run_invocation(TrustedTransport(ORIGIN, TOKEN, invocation), model=scripted_model(lambda *_: uses),
                                  http_transport=httpx.ASGITransport(app_for(path, [datetime.now(UTC)])))
    assert result.interruption is None
    with Store(path) as store:
        assert store.get_invocation(invocation).status == "ERROR"


@pytest.mark.asyncio
async def test_observed_wall_deadline_without_control_loss_stays_terminal(tmp_path, monkeypatch):
    import asyncio

    from strands.agent.agent import Agent as OfflineAgent
    monkeypatch.setattr(core, "Agent", OfflineAgent)
    path, invocation = seeded(tmp_path)
    model = scripted_model(lambda *_: [])
    original = model.stream
    async def slow(*args, **kwargs):
        await asyncio.sleep(2)
        async for event in original(*args, **kwargs):
            yield event
    monkeypatch.setattr(model, "stream", slow)
    result = await run_invocation(TrustedTransport(ORIGIN, TOKEN, invocation, deadline_seconds=1), model=model,
        http_transport=httpx.ASGITransport(app_for(path, [datetime.now(UTC)])))
    assert result.error_code == "DEADLINE_EXCEEDED"
    assert result.interruption is None
    with Store(path) as store:
        assert store.get_invocation(invocation).status == "ERROR"
