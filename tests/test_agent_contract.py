"""Offline provider/HTTP boundaries: real hooks, no external construction."""
import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from agent.case_contracts import CaseContext, EventSummary
from agent.tools.durable import DurableLifecycle


def packet(**updates):
    return CaseContext(invocation_id="inv-1", invocation_revision=0,
        invocation_status="PENDING", district_id="south_loop_demo", current_policy_version="v1",
        trigger=EventSummary(id=1, event_type="SIGNAL_RECEIVED", timestamp=datetime.now(UTC),
                             signal_id="sig-1"), **updates)


class Client:
    transport = SimpleNamespace(invocation_id="inv-1")
    def __init__(self, packets):
        self.packets = iter(packets)
        self.commands = []
    async def execute(self, command, *, call_ref=None):
        self.commands.append((command, call_ref))
        return {"outcome": "OK", "data": next(self.packets).model_dump(mode="json")}


def test_fresh_context_replaces_packet_keeps_history_and_stops_before_next_call():
    from agent.core import InvocationHooks
    from agent.prompts import PROMPT_VERSION
    async def run():
        client = Client([packet(), packet(saved_stop="EXCEPTION_RAISED")])
        hooks = InvocationHooks(client, deadline_at=float("inf"))
        agent = SimpleNamespace(system_prompt="old", messages=[{"role": "assistant", "content": []}])
        event = SimpleNamespace(agent=agent, cancel=False)
        await hooks.before_model(event)
        assert not event.cancel and hooks.model_cycles == 1
        assert PROMPT_VERSION in agent.system_prompt
        assert len(agent.messages) == 1
        await hooks.before_model(event)
        assert event.cancel and hooks.model_cycles == 1
        assert len(client.commands) == 2
        assert client.commands[0][0].operation == "read_case_context"
        assert client.commands[0][1] != client.commands[1][1]
    asyncio.run(run())


def test_no_result_context_or_gate_failure_prevents_model():
    from agent.core import InvocationHooks
    async def run():
        class Broken(Client):
            async def execute(self, *args, **kwargs):
                return {"outcome": "ERROR", "data": None}
        event = SimpleNamespace(agent=SimpleNamespace(system_prompt="", messages=[]), cancel=False)
        hooks = InvocationHooks(Broken([]), deadline_at=float("inf"))
        await hooks.before_model(event)
        assert event.cancel and hooks.model_cycles == 0
    asyncio.run(run())


def test_actual_agent_factory_has_isolated_domain_registry(monkeypatch):
    from strands.tools.executors import SequentialToolExecutor

    from agent import core
    from agent.tools.client import TrustedTransport
    from agent.tools.session import build_steward_tool_session
    captured = []
    def factory(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(**kwargs)
    monkeypatch.setattr(core, "Agent", factory)
    session = build_steward_tool_session(TrustedTransport("http://localhost:8000", "private", "inv-1"))
    first = core.build_agent(session, model=object())
    second = core.build_agent(session, model=object())
    assert first is not second
    assert first.callback_handler is None and first.retry_strategy is None
    assert isinstance(first.tool_executor, SequentialToolExecutor)
    assert len(first.tools) == 25
    assert not {"current_time", "example"} & {tool.tool_name for tool in first.tools}
    assert first.hooks[0] is not second.hooks[0]
    asyncio.run(session.client.aclose())


def scripted_model(script):
    from strands.models.model import Model
    class Scripted(Model):
        def __init__(self):
            self.calls = []
        def update_config(self, **kwargs):
            pass
        def get_config(self):
            return {"model_id": "offline-script"}
        async def structured_output(self, *args, **kwargs):
            raise AssertionError("no alternate model path")
            yield
        async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
            self.calls.append((list(messages), system_prompt))
            uses = script(len(self.calls), messages, system_prompt)
            yield {"messageStart": {"role": "assistant"}}
            for i, (name, values) in enumerate(uses):
                yield {"contentBlockStart": {"contentBlockIndex": i,
                    "start": {"toolUse": {"toolUseId": f"call-{len(self.calls)}-{i}", "name": name}}}}
                yield {"contentBlockDelta": {"contentBlockIndex": i, "delta": {"toolUse": {"input": json.dumps(values)}}}}
                yield {"contentBlockStop": {"contentBlockIndex": i}}
            yield {"messageStop": {"stopReason": "tool_use" if uses else "end_turn"}}
            yield {"metadata": {"usage": {"inputTokens": 5, "outputTokens": 5, "totalTokens": 10},
                                "metrics": {"latencyMs": 1}}}
    return Scripted()


def test_real_agent_http_monitor_intent_is_not_stop_but_effect_suppresses_same_batch(tmp_path, monkeypatch):
    from pathlib import Path

    import httpx
    from strands.agent.agent import Agent as OfflineAgent
    from test_api_auth import ORIGIN, SIGNING, TOKEN

    from agent import core
    from agent.api import create_app
    from agent.config import ApiSettings
    from agent.seed import _seed
    from agent.store import Store
    from agent.tools.client import TrustedTransport
    from agent.tools.session import build_steward_tool_session
    path = tmp_path / "seed.sqlite3"
    _seed(path, Path("data"))
    with Store(path) as store:
        invocation = store.pending_invocations()[0]
    app = create_app(ApiSettings(store_path=path, origin=ORIGIN, local_http=True,
                                service_token=TOKEN, session_secret=SIGNING))
    requests = []
    class Transport(httpx.ASGITransport):
        async def handle_async_request(self, request):
            requests.append((request.method, request.url.path))
            return await super().handle_async_request(request)
    def script(cycle, messages, prompt):
        case = json.loads(prompt.split("<untrusted_case_json>\n")[1].split("\n</untrusted_case_json>")[0])
        if cycle == 1:
            return [("record_investigation_decision", {"issue_id": "demo-couch", "decision_type": "MONITOR",
                "expected_issue_revision": case["issue"]["state_revision"], "summary": "Await an independent observation."})]
        assert cycle == 2, messages[-1]  # no final narration/model call after actual saved watch
        previous = next(b["toolResult"] for m in reversed(messages) for b in m["content"] if "toolResult" in b)
        decision_id = previous["content"][0]["json"]["data"]["record_id"]
        return [("apply_investigation_decision", {"issue_id": "demo-couch", "decision_id": decision_id,
                    "expected_issue_revision": case["issue"]["state_revision"]}), ("get_budget", {})]
    model = scripted_model(script)
    monkeypatch.setattr(core, "Agent", OfflineAgent)  # real engine with only injected offline model
    async def run():
        async with build_steward_tool_session(TrustedTransport(ORIGIN, TOKEN, invocation.id),
                                              lifecycle_factory=DurableLifecycle,
                                              http_transport=Transport(app=app)) as session:
            await session.client.lifecycle.acquire()
            agent = core.build_agent(session, model=model, lifecycle=session.client.lifecycle)
            await agent.invoke_async("Process the saved trigger.")
            assert agent.steward_hooks.stopped == "INVESTIGATION_ACTION_APPLIED"
            assert agent.steward_hooks.model_cycles == 2
            assert agent.steward_hooks.host_reads >= 3
            assert agent.steward_hooks.tool_requests == 3
            assert agent.steward_hooks.usage.totalTokens == 20
    asyncio.run(run())
    assert ("GET", "/api/budget") not in requests
    with Store(path) as store:
        assert store.get_issue_record("demo-couch").status == "MONITORING"


def test_provider_observation_is_safe_counted_and_unregistered():
    from agent.core import ProviderObserver
    class Events:
        def __init__(self):
            self.callbacks = {}
        def register_last(self, name, callback, **kwargs):
            self.callbacks[name] = callback
        def unregister(self, name, **kwargs):
            del self.callbacks[name]
    events = Events()
    observed = []
    observer = ProviderObserver(SimpleNamespace(client=SimpleNamespace(meta=SimpleNamespace(events=events))),
                                "inv-1", observed.append)
    observer.start()
    for callback in events.callbacks.values():
        callback(request={"Authorization": "must-never-appear", "body": "hidden"})
    assert [x.ordinal for x in observed] == [1, 2]
    assert all(x.kind == "sdk_before_send" for x in observed)
    assert "hidden" not in repr(observed) and "Authorization" not in repr(observed)
    observer.close()
    assert events.callbacks == {}


def test_real_engine_denial_continues_to_exception_then_stops(tmp_path, monkeypatch):
    import httpx
    from strands.agent.agent import Agent as OfflineAgent
    from test_inspection import proof_ready_job, valid_findings
    from test_investigation import ORIGIN, TOKEN
    from test_investigation_repair import client_for

    from agent import core
    from agent.store import Store
    from agent.tools.client import TrustedTransport
    from agent.tools.session import build_steward_tool_session
    job_id, proof_id = proof_ready_job(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        invocation = store.invocation_for_event(store.proof_event_for_submission(proof_id).id)
    def partial(*args):
        value = valid_findings()
        value["findings"]["area_clear"] = False
        return value
    with client_for(tmp_path, completion_inspector=partial) as client:
        app = client.app
    def script(cycle, messages, prompt):
        case = json.loads(prompt.split("<untrusted_case_json>\n")[1].split("\n</untrusted_case_json>")[0])
        revision = case["jobs"][0]["state_revision"]
        common = {"job_id": job_id, "submission_id": proof_id, "expected_job_revision": revision}
        if cycle == 1:
            return [("inspect_completion", common)]
        if cycle == 2:
            assert case["verifications"][0]["total"] == 90
            return [("release_payment", common)]
        basis = {**common, "kind": "completion_operator", "verification_id": case["verifications"][0]["id"],
                 "denial_event_id": case["latest_denial"]["id"]}
        if cycle == 3:
            return [("record_operational_decision", {"issue_id": "issue", "decision_type": "REQUEST_OPERATOR",
                "summary": "Remaining cleanup is required by the original contract.", "basis": basis})]
        assert cycle == 4
        basis["kind"] = "completion"
        basis["reason_code"] = "completion_incomplete"
        return [("escalate_to_operator", {"basis": basis}), ("get_budget", {})]
    monkeypatch.setattr(core, "Agent", OfflineAgent)
    async def run():
        async with build_steward_tool_session(TrustedTransport(ORIGIN, TOKEN, invocation.id),
            lifecycle_factory=DurableLifecycle,
            http_transport=httpx.ASGITransport(app=app)) as session:
            await session.client.lifecycle.acquire()
            model = scripted_model(script)
            agent = core.build_agent(session, model=model, lifecycle=session.client.lifecycle)
            result = await core.invoke_case(agent)
            assert result.error_code is None, result
            assert result.saved_stop == "EXCEPTION_RAISED"
            assert result.model_cycles == 4
            assert result.tool_requests == 5
    asyncio.run(run())
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job_id).status == "PROOF_SUBMITTED"
        assert store.open_completion_exception(job_id).status == "PENDING"
        assert store.payment_for_job(job_id) is None


def test_awaited_authorization_and_ack_refusal_prevent_new_model_and_tool_work():
    from agent.core import InvocationHooks
    class Refuse:
        def __init__(self, mode):
            self.mode = mode
            self.calls = []
        async def authorize(self, event):
            self.calls.append(("authorize", event.kind))
            return event.kind != self.mode
        async def observe(self, event):
            self.calls.append(("observe", event.kind))
            return self.mode != "ack"
    async def run():
        for mode in ("context", "model", "ack"):
            lifecycle = Refuse(mode)
            client = Client([packet()])
            hooks = InvocationHooks(client, deadline_at=float("inf"), lifecycle=lifecycle)
            event = SimpleNamespace(agent=SimpleNamespace(system_prompt="original"), cancel=False)
            await hooks.before_model(event)
            assert event.cancel and hooks.model_cycles == 0
            if mode == "context":
                assert not client.commands
            tool = SimpleNamespace(tool_use={"name": "get_budget", "input": {}, "toolUseId": "x"}, cancel_tool=False)
            await hooks.before_tool(tool)
            assert tool.cancel_tool
    asyncio.run(run())


def test_model_and_tool_caps_are_separate_from_host_reads():
    from agent.core import InvocationHooks
    async def run():
        hooks = InvocationHooks(Client([packet()] * 12), deadline_at=float("inf"))
        event = SimpleNamespace(agent=SimpleNamespace(system_prompt=""), cancel=False)
        for _ in range(12):
            await hooks.before_model(event)
            assert not event.cancel
        await hooks.before_model(event)
        assert event.cancel == "MODEL_CYCLE_LIMIT" and hooks.host_reads == 12
        tools = InvocationHooks(Client([]), deadline_at=float("inf"))
        for i in range(40):
            event = SimpleNamespace(tool_use={"name": "get_budget", "input": {}, "toolUseId": str(i)}, cancel_tool=False)
            await tools.before_tool(event)
            assert not event.cancel_tool
        await tools.before_tool(event)
        assert event.cancel_tool == "TOOL_REQUEST_LIMIT"
    asyncio.run(run())


def test_bounded_invoke_times_out_stalled_fake_provider_without_cost_claim(monkeypatch):
    from time import monotonic

    import httpx
    from strands.agent.agent import Agent as OfflineAgent
    from test_http_tool_integration import result

    from agent import core
    from agent.tools.client import TrustedTransport
    from agent.tools.session import build_steward_tool_session
    model = scripted_model(lambda *_: [])
    async def stalled(*args, **kwargs):
        await asyncio.sleep(10)
        yield {"messageStart": {"role": "assistant"}}
    model.stream = stalled
    monkeypatch.setattr(core, "Agent", OfflineAgent)
    async def run():
        async with build_steward_tool_session(TrustedTransport("http://localhost:8000", "private", "inv-1"),
                http_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result(packet().model_dump(mode="json"))))) as session:
            agent = core.build_agent(session, model=model, deadline_at=monotonic() + .15)
            start = monotonic()
            outcome = await core.invoke_case(agent)
            assert monotonic() - start < 2
            assert outcome.error_code == "DEADLINE_EXCEEDED"
            assert outcome.saved_stop is None
    asyncio.run(run())


def test_cli_submits_real_human_event_without_constructing_agent(tmp_path, monkeypatch, capsys):
    from fastapi.testclient import TestClient
    from test_api_auth import ORIGIN, SIGNING, TOKEN

    from agent import cli
    from agent.api import create_app
    from agent.config import ApiSettings
    from agent.store import Store
    app = create_app(ApiSettings(store_path=tmp_path / "cli.sqlite3", origin=ORIGIN,
        local_http=True, session_secret=SIGNING, service_token=TOKEN))
    monkeypatch.setattr(cli.httpx, "Client", lambda **kwargs: TestClient(app, base_url=ORIGIN))
    assert cli.main(["--origin", ORIGIN, "submit", "--description", "A blocked sidewalk",
                     "--location", "State St & Madison St (demo)", "--key", "cli-exact-key"]) == 0
    with Store(tmp_path / "cli.sqlite3") as store:
        pending = store.pending_invocations()
        assert len(pending) == 1 and pending[0].trigger_type == "SIGNAL_RECEIVED"
        assert store.get_event(pending[0].trigger_event_id).actor.actor_type == "resident"
    assert TOKEN not in capsys.readouterr().out


def test_context_dto_import_does_not_load_server_database_or_sdk():
    import os
    import subprocess
    import sys
    code = "import offline_guard; import sys; import agent.case_contracts; assert not {'agent.store', 'agent.api', 'fastapi'} & sys.modules.keys()"
    result = subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": "tests"},
                            capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("command", ["context", "resume"])
def test_cli_service_origin_override_rejected_before_credential_client(monkeypatch, command, capsys):
    from agent import cli
    monkeypatch.setenv("STEWARD_ORIGIN", "https://configured.example")
    monkeypatch.setenv("STEWARD_SERVICE_TOKEN", "ambient-private-service-token")
    calls = []
    async def read(*args, **kwargs):
        calls.append(args)
        return {"outcome": "OK", "data": {}}
    monkeypatch.setattr(cli, "read_case", read)
    monkeypatch.setattr(cli, "resume_case", read)
    assert cli.main(["--origin", "https://different.example", command, "inv-1"]) != 0
    assert calls == []
    assert "ambient-private-service-token" not in capsys.readouterr().out


@pytest.mark.parametrize("configured", [None, "https://configured.example"])
@pytest.mark.parametrize("command", ["context", "resume"])
def test_cli_service_configured_or_default_origin_uses_bound_destination(monkeypatch, configured, command):
    from agent import cli
    if configured is None:
        monkeypatch.delenv("STEWARD_ORIGIN", raising=False)
    else:
        monkeypatch.setenv("STEWARD_ORIGIN", configured)
    monkeypatch.setenv("STEWARD_SERVICE_TOKEN", "ambient-private-service-token")
    origin = configured or "http://127.0.0.1:8000"
    calls = []
    async def read(*args, **kwargs):
        calls.append(args)
        return {"outcome": "OK", "data": {}}
    monkeypatch.setattr(cli, "read_case", read)
    monkeypatch.setattr(cli, "resume_case", read)
    assert cli.main(["--origin", origin, command, "inv-1"]) == (0 if command == "context" else 2)
    assert calls == [(origin, "ambient-private-service-token", "inv-1")]


def test_malformed_tool_input_cancels_only_that_call_and_counts_against_budget(tmp_path, monkeypatch):
    """A basis-kind slip returns its reason to the model instead of ending the invocation."""
    from pathlib import Path

    import httpx
    from strands.agent.agent import Agent as OfflineAgent
    from test_api_auth import ORIGIN, SIGNING, TOKEN

    from agent import core
    from agent.api import create_app
    from agent.config import ApiSettings
    from agent.seed import _seed
    from agent.store import Store
    from agent.tools.client import TrustedTransport
    from agent.tools.session import build_steward_tool_session
    path = tmp_path / "seed.sqlite3"
    _seed(path, Path("data"))
    with Store(path) as store:
        invocation = store.pending_invocations()[0]
    app = create_app(ApiSettings(store_path=path, origin=ORIGIN, local_http=True,
                                service_token=TOKEN, session_secret=SIGNING))
    seen = {}

    def script(cycle, messages, prompt):
        case = json.loads(prompt.split("<untrusted_case_json>\n")[1].split("\n</untrusted_case_json>")[0])
        if cycle == 1:
            return [("record_operational_decision", {"issue_id": "demo-couch", "decision_type": "REQUEST_OPERATOR",
                "summary": "wrong basis kind", "evidence_ids": [], "basis": {"kind": "settlement", "job_id": "job",
                "submission_id": "sub", "verification_id": "ver", "expected_job_revision": 1}})]
        previous = next(b["toolResult"] for m in reversed(messages) for b in m["content"] if "toolResult" in b)
        if cycle == 2:
            seen["result"] = previous
            return [("record_investigation_decision", {"issue_id": "demo-couch", "decision_type": "MONITOR",
                "expected_issue_revision": case["issue"]["state_revision"], "summary": "Await an independent observation."})]
        assert cycle == 3, messages[-1]
        decision_id = previous["content"][0]["json"]["data"]["record_id"]
        return [("apply_investigation_decision", {"issue_id": "demo-couch", "decision_id": decision_id,
                    "expected_issue_revision": case["issue"]["state_revision"]})]
    model = scripted_model(script)
    monkeypatch.setattr(core, "Agent", OfflineAgent)

    async def run():
        async with build_steward_tool_session(TrustedTransport(ORIGIN, TOKEN, invocation.id),
                                              lifecycle_factory=DurableLifecycle,
                                              http_transport=httpx.ASGITransport(app=app)) as session:
            await session.client.lifecycle.acquire()
            agent = core.build_agent(session, model=model, lifecycle=session.client.lifecycle)
            await agent.invoke_async("Process the saved trigger.")
            assert agent.steward_hooks.stopped == "INVESTIGATION_ACTION_APPLIED"
            assert agent.steward_hooks.model_cycles == 3
            assert agent.steward_hooks.tool_requests == 3
    asyncio.run(run())
    rendered = json.dumps(seen["result"])
    assert seen["result"]["status"] == "error"
    assert "INVALID_TOOL_INPUT" in rendered and "does not match basis" in rendered
    with Store(path) as store:
        assert store.get_issue_record("demo-couch").status == "MONITORING"
