"""Durable coordinator tests use real saved triggers, isolated SQLite and fake clocks."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent.seed import _seed
from agent.store import Store
from agent.tools.protocol import build_command


def seeded(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    _seed(path, Path("data"))
    with Store(path) as store:
        return path, store.pending_invocations()[0].id


def authorize_command(co, claim, command):
    from agent.runtime_contracts import command_record
    co.execution(claim, f"authorize-{claim.fence}-model-1", "model", 1)
    co.execution(claim, f"authorize-{claim.fence}-tool-1", "tool", 1,
                 details={"command": command_record(command).model_dump(mode="json")})
    return "model-1-tool-1"


def test_claim_restart_preserves_deadline_and_two_episode_lifetime(tmp_path):
    from agent.coordinator import Coordinator, RuntimeConflict
    path, invocation = seeded(tmp_path)
    now = datetime(2030, 1, 1, tzinfo=UTC)
    with Store(path) as store:
        co = Coordinator(store, clock=lambda: now)
        first = co.claim(invocation, "owner-a", "claim-a")
        assert first.episode == 1
        with pytest.raises(RuntimeConflict, match="CLAIM_BUSY"):
            co.claim(invocation, "owner-b", "claim-b")
    now += timedelta(seconds=35)
    with Store(path) as store:
        second = Coordinator(store, clock=lambda: now).claim(invocation, "owner-b", "claim-b")
        assert second.deadline == first.deadline
        assert second.fence > first.fence
    now += timedelta(seconds=300)
    with Store(path) as store:
        co = Coordinator(store, clock=lambda: now)
        third = co.claim(invocation, "owner-c", "claim-c")
        assert third.episode == 2
        now += timedelta(seconds=300)
        with pytest.raises(RuntimeConflict, match="EPISODES_EXHAUSTED"):
            co.claim(invocation, "owner-d", "claim-d")
        assert store.get_invocation(invocation).status == "ERROR"
        assert store.get_invocation(invocation).error_code == "EPISODES_EXHAUSTED"


def test_prepared_identity_attempt_nonce_and_stale_owner(tmp_path):
    from agent.coordinator import Coordinator, RuntimeConflict
    path, invocation = seeded(tmp_path)
    now = datetime(2030, 1, 1, tzinfo=UTC)
    command = build_command("get_budget", {})
    with Store(path) as store:
        co = Coordinator(store, clock=lambda: now)
        claim = co.claim(invocation, "owner-a", "claim-a")
        ref = authorize_command(co, claim, command)
        saved = co.prepare(claim, ref, command)
        assert co.prepare(claim, ref, command) == saved
        attempt = co.begin(claim, saved.id, "attempt-nonce")
        assert co.begin(claim, saved.id, "attempt-nonce") == attempt
        now += timedelta(seconds=35)
        takeover = co.claim(invocation, "owner-b", "claim-b")
        with pytest.raises(RuntimeConflict, match="FENCED"):
            co.begin(claim, saved.id, "old-owner")
        assert co.load(takeover, saved.id).deadline == saved.deadline
        assert co.attempt_count(saved.id) == 1


def test_normal_wait_is_dormant_not_recoverable(tmp_path):
    from agent.coordinator import Coordinator, RuntimeConflict
    path, invocation = seeded(tmp_path)
    now = datetime(2030, 1, 1, tzinfo=UTC)
    with Store(path) as store:
        co = Coordinator(store, clock=lambda: now)
        claim = co.claim(invocation, "owner-a", "claim-a")
        co.complete(claim, "WAITING", "MONITOR")
        now += timedelta(days=1)
        with pytest.raises(RuntimeConflict, match="INVOCATION_TERMINAL"):
            co.claim(invocation, "owner-b", "claim-b")


def test_caller_cannot_extend_saved_episode_deadline(tmp_path):
    from agent.coordinator import Coordinator, RuntimeConflict
    path, invocation = seeded(tmp_path)
    with Store(path) as store:
        co = Coordinator(store)
        claim = co.claim(invocation, "owner-a", "claim-a")
        forged = claim.model_copy(update={"deadline": claim.deadline + timedelta(days=1)})
        with pytest.raises(RuntimeConflict, match="FENCED"):
            co.prepare(forged, "forged", build_command("get_budget", {}))
        with pytest.raises(RuntimeConflict, match="FENCED"):
            co.renew(forged)


@pytest.mark.asyncio
async def test_actual_asgi_durable_client_persists_before_send_and_ack(tmp_path):
    import httpx
    from test_api_auth import ORIGIN, SIGNING, TOKEN

    from agent.api import create_app
    from agent.config import ApiSettings
    from agent.core import ExecutionRequest
    from agent.tools.client import TrustedTransport
    from agent.tools.durable import DurableLifecycle
    from agent.tools.session import build_steward_tool_session
    path, invocation = seeded(tmp_path)
    app = create_app(ApiSettings(store_path=path, origin=ORIGIN, local_http=True,
        session_secret=SIGNING, service_token=TOKEN))
    async with build_steward_tool_session(TrustedTransport(ORIGIN, TOKEN, invocation),
            lifecycle_factory=DurableLifecycle, http_transport=httpx.ASGITransport(app)) as session:
        life = session.client.lifecycle
        await life.acquire()
        command = build_command("get_budget", {})
        assert await life.authorize(ExecutionRequest("model", 1, invocation))
        assert await life.authorize(ExecutionRequest("tool", 1, invocation, call_ref="provider-reused", command=command))
        result = await session.client.execute(command, call_ref="provider-reused")
        assert result["outcome"] == "OK", result
        with Store(path) as store:
            from agent.coordinator import Coordinator
            requests = Coordinator(store).requests(life.claim)
            assert len(requests) == 1
            assert requests[0].terminal_json is not None
            assert store.db.execute("SELECT COUNT(*) FROM runtime_observations").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_real_runner_monitor_then_dormant_with_same_batch_suppression(tmp_path, monkeypatch):
    import json

    import httpx
    from strands.agent.agent import Agent as OfflineAgent
    from test_agent_contract import scripted_model
    from test_api_auth import ORIGIN, SIGNING, TOKEN

    from agent import core
    from agent.api import create_app
    from agent.config import ApiSettings
    from agent.runtime import run_invocation
    from agent.tools.client import TrustedTransport
    path, invocation = seeded(tmp_path)
    app = create_app(ApiSettings(store_path=path, origin=ORIGIN, local_http=True,
        session_secret=SIGNING, service_token=TOKEN))
    def script(cycle, messages, prompt):
        case = json.loads(prompt.split("<untrusted_case_json>\n")[1].split("\n</untrusted_case_json>")[0])
        if cycle == 1:
            return [("record_investigation_decision", {"issue_id": "demo-couch", "decision_type": "MONITOR",
                "expected_issue_revision": case["issue"]["state_revision"], "summary": "Await independent evidence."})]
        assert cycle == 2
        prior = next(b["toolResult"] for m in reversed(messages) for b in m["content"] if "toolResult" in b)
        return [("apply_investigation_decision", {"issue_id": "demo-couch", "decision_id": prior["content"][0]["json"]["data"]["record_id"],
                 "expected_issue_revision": case["issue"]["state_revision"]}), ("get_budget", {})]
    monkeypatch.setattr(core, "Agent", OfflineAgent)
    result = await run_invocation(TrustedTransport(ORIGIN, TOKEN, invocation), model=scripted_model(script),
                                  http_transport=httpx.ASGITransport(app))
    assert result.saved_stop == "INVESTIGATION_ACTION_APPLIED", result
    with Store(path) as store:
        assert store.get_invocation(invocation).status == "WAITING"
        assert store.get_issue_record("demo-couch").status == "MONITORING"
        assert store.db.execute("SELECT COUNT(*) FROM runtime_requests WHERE json_extract(record_json,'$.command.operation')='get_budget'").fetchone()[0] == 0


def test_populated_schema_six_upgrade_preserves_bytes_and_rolls_back(tmp_path, monkeypatch):
    import sqlite3

    from agent import migrations
    path = tmp_path / "schema-six.sqlite3"
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "SCHEMA_VERSION", 6)
        patch.setattr(migrations, "_upgrade_seven", lambda db: None)
        _seed(path, Path("data"))
    def rows():
        with sqlite3.connect(path) as db:
            return {table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                    for table in ("events", "signals", "issues", "signal_receipts", "request_receipts", "invocations", "seed_receipts")}
    before = rows()
    original = migrations._upgrade_seven
    def failed(db):
        original(db)
        raise RuntimeError("injected upgrade failure")
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "_upgrade_seven", failed)
        with pytest.raises(RuntimeError, match="injected"):
            Store(path)
    assert rows() == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        assert db.execute("SELECT name FROM sqlite_master WHERE name='runtime_state'").fetchone() is None
    with Store(path) as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 7
        assert not store.db.execute("PRAGMA foreign_key_check").fetchall()
    assert rows() == before


def test_exhausted_run_preserves_read_only_reconciliation_and_refuses_new_work(tmp_path):
    from agent.coordinator import Coordinator, RuntimeConflict
    path, invocation = seeded(tmp_path)
    now = datetime.now(UTC)
    with Store(path) as store:
        co = Coordinator(store, clock=lambda: now)
        claim = co.claim(invocation, "owner", "claim")
        command = build_command("get_budget", {})
        saved = co.prepare(claim, authorize_command(co, claim, command), command)
        co.begin(claim, saved.id, "attempt")
        with store.transaction():
            store.db.execute("UPDATE runtime_state SET model_cycles=12 WHERE invocation_id=?", (invocation,))
        now += timedelta(seconds=35)
        with pytest.raises(RuntimeConflict, match="LIFETIME_LIMIT_EXHAUSTED"):
            co.claim(invocation, "next", "next")
        assert store.get_invocation(invocation).status == "ERROR"
        assert co.reconcile(claim, saved.id).terminal_json is not None
        with pytest.raises(RuntimeConflict, match="FENCED"):
            co.begin(claim, saved.id, "forbidden")


def test_competing_claims_have_one_saved_owner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from agent.coordinator import Coordinator, RuntimeConflict
    path, invocation = seeded(tmp_path)
    start = Barrier(2)
    def acquire(owner):
        with Store(path) as store:
            start.wait(timeout=5)
            try:
                return Coordinator(store).claim(invocation, owner, owner)
            except RuntimeConflict as error:
                return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(acquire, ("one", "two")))
    assert results.count("CLAIM_BUSY") == 1
    with Store(path) as store:
        inv = store.get_invocation(invocation)
        winner = next(value for value in results if value != "CLAIM_BUSY")
        assert (inv.lease_owner, inv.fencing_token) == (winner.owner, winner.fence)


def test_unknown_reservations_consume_three_attempts_across_takeovers(tmp_path):
    from agent.coordinator import Coordinator, RuntimeConflict
    path, invocation = seeded(tmp_path)
    now = datetime.now(UTC)
    with Store(path) as store:
        co = Coordinator(store, clock=lambda: now)
        claim = co.claim(invocation, "owner-1", "claim-1")
        command = build_command("get_budget", {})
        saved = co.prepare(claim, authorize_command(co, claim, command), command)
        for ordinal in range(1, 4):
            if ordinal > 1:
                now += timedelta(seconds=31)
                claim = co.claim(invocation, f"owner-{ordinal}", f"claim-{ordinal}")
            attempt = co.begin(claim, saved.id, f"send-{ordinal}")
            assert attempt.ordinal == ordinal
            assert co.begin(claim, saved.id, f"send-{ordinal}") == attempt
        now += timedelta(seconds=31)
        claim = co.claim(invocation, "owner-4", "claim-4")
        with pytest.raises(RuntimeConflict, match="ATTEMPTS_EXHAUSTED"):
            co.begin(claim, saved.id, "send-4")
        assert co.load(claim, saved.id).deadline == saved.deadline
        assert co.attempt_count(saved.id) == 3
        assert store.db.execute("SELECT COUNT(*) FROM runtime_observations").fetchone()[0] == 0
