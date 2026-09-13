import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from agent import contracts as c
from agent.models import Signal
from agent.store import Store

ACTOR = c.ActorContext(actor_id="intake-service", actor_type="service", label="Feed adapter")


def receive(store, signal=None, key="intake-1", invocation_id="run-1"):
    return store.receive_signal(
        signal or report(),
        context=c.MutationContext(actor=ACTOR, operation="receive_signal", idempotency_key=key),
        invocation=c.PendingInvocationSpec(id=invocation_id, trigger_type="SIGNAL_RECEIVED",
                                           policy_version="south-loop-v3"),
    )


def report(signal_id="s1", author="resident-1", text="Couch blocks sidewalk"):
    return Signal.from_dict({
        "id": signal_id,
        "source": "demo_feed",
        "source_author_id": author,
        "raw_text": text,
        "reported_location": "1530 S Michigan Ave",
        "received_at": "2026-09-12T15:00:00Z",
        "observed_at": "2026-09-12T14:00:00Z",
        "provenance": "seeded",
        "image_sha256": "a" * 64 if signal_id == "s1" else None,
    })


def setup_store(path):
    store = Store(path)
    store.create_issue("couch", "bulky_waste", "1530 S Michigan Ave")
    store.record_geocode("couch", accuracy_m=10, provenance="seeded")
    return store


def test_resume_and_retry_preserve_evidence_without_inventing_agent_decision(tmp_path):
    path = tmp_path / "state.sqlite3"
    with setup_store(path) as store:
        first = store.add_signal("couch", report())
        assert first["evidence_score"] == 65
        assert first["status"] == "CANDIDATE"
        count = len(store.events("couch"))
        assert store.add_signal("couch", report()) == first
        assert len(store.events("couch")) == count
    with Store(path) as resumed:
        result = resumed.add_signal("couch", report("s2", "resident-2", "Sofa and bags remain"))
        assert result["evidence_score"] == 85
        assert len(result["signal_ids"]) == 2
        assert result["status"] == "CANDIDATE"
        assert resumed.events("couch")[-1]["payload"]["score"]["total"] == 85


def test_conflicting_retry_and_double_link_do_not_mutate(tmp_path):
    with setup_store(tmp_path / "state.sqlite3") as store:
        original = store.add_signal("couch", report())
        events = store.events("couch")
        with pytest.raises(ValueError, match="conflict"):
            store.add_signal("couch", report(text="Changed content"))
        store.create_issue("other", "litter", "Elsewhere")
        with pytest.raises(ValueError, match="already linked"):
            store.add_signal("other", report())
        assert store.get_issue("couch") == original
        assert store.events("couch") == events
        assert store.get_issue("other")["signal_ids"] == []


def test_failed_audit_write_rolls_back_signal_and_score(tmp_path):
    path = tmp_path / "state.sqlite3"
    with setup_store(path) as store:
        original = store.get_issue("couch")
        with sqlite3.connect(path) as conn:
            conn.execute("""CREATE TRIGGER reject_event BEFORE INSERT ON events
                BEGIN SELECT RAISE(ABORT, 'test audit failure'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="test audit failure"):
            store.add_signal("couch", report())
        assert store.get_issue("couch") == original
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT count(*) FROM signals").fetchone()[0] == 0


COMPLETED = {
    "id": "demo-service-1", "status": "COMPLETED", "provenance": "seeded",
    "completed_at": "2026-09-11T20:41:00Z",
}


def test_completed_record_is_a_pending_conflict_until_two_newer_observations(tmp_path):
    with setup_store(tmp_path / "state.sqlite3") as store:
        store.add_signal("couch", report())
        result = store.record_service_match("couch", COMPLETED)
        assert result["evidence_score"] == 65
        assert result["service_record"]["conflict"] == "pending"
        assert result["service_record"]["completed_at"] == "2026-09-11T20:41:00+00:00"
        assert store.events("couch")[-1]["event_type"] == "SERVICE_MATCH_RECORDED"
        with pytest.raises(ValueError, match="not supported"):
            store.confirm_official_dispute("couch")
        corroborated = store.add_signal("couch", report("s2", "resident-2", "Sofa and bags remain"))
        assert corroborated["evidence_score"] == 85
        disputed = store.confirm_official_dispute("couch")
        assert disputed["evidence_score"] == 100
        assert disputed["service_record"]["conflict"] == "disputed"
        assert disputed["status"] == "CANDIDATE"
        events = store.events("couch")
        assert events[-1]["event_type"] == "OFFICIAL_STATUS_DISPUTED"
        assert events[-1]["payload"]["score"]["total"] == 100
        assert store.confirm_official_dispute("couch") == disputed
        assert store.record_service_match("couch", COMPLETED) == disputed
        assert store.events("couch") == events


def test_open_record_corroborates_and_cannot_be_disputed(tmp_path):
    with setup_store(tmp_path / "state.sqlite3") as store:
        store.add_signal("couch", report())
        result = store.record_service_match(
            "couch", {**COMPLETED, "status": "OPEN", "completed_at": None}
        )
        assert result["evidence_score"] == 80
        assert result["service_record"]["conflict"] == "none"
        with pytest.raises(ValueError, match="no completed"):
            store.confirm_official_dispute("couch")


@pytest.mark.parametrize("record", [
    {**COMPLETED, "status": "DONE"},
    {**COMPLETED, "completed_at": None},
    {**COMPLETED, "provenance": "maybe"},
    {**COMPLETED, "conflict": "disputed"},
    {k: v for k, v in COMPLETED.items() if k != "provenance"},
])
def test_invalid_service_records_do_not_mutate(tmp_path, record):
    with setup_store(tmp_path / "state.sqlite3") as store:
        store.add_signal("couch", report())
        before = store.get_issue("couch")
        events = store.events("couch")
        with pytest.raises(ValueError):
            store.record_service_match("couch", record)
        assert store.get_issue("couch") == before
        assert store.events("couch") == events


@pytest.mark.parametrize("accuracy", [-1, float("nan"), float("inf"), True])
def test_invalid_geocode_cannot_manufacture_points(tmp_path, accuracy):
    with setup_store(tmp_path / "state.sqlite3") as store:
        before = store.get_issue("couch")
        with pytest.raises(ValueError):
            store.record_geocode("couch", accuracy_m=accuracy, provenance="seeded")
        assert store.get_issue("couch") == before


def test_unknown_issue_and_reserved_terminal_state_reject_linking(tmp_path):
    path = tmp_path / "state.sqlite3"
    with setup_store(path) as store:
        with pytest.raises(KeyError):
            store.add_signal("missing", report())
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE issues SET status = 'RESOLVED' WHERE id = 'couch'")
        with pytest.raises(ValueError, match="closed"):
            store.add_signal("couch", report())


def test_database_created_by_newer_schema_is_not_modified(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 99")
    with pytest.raises(ValueError, match="schema"):
        Store(path)


def test_concurrent_duplicate_deliveries_commit_once(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    with setup_store(path):
        pass

    def deliver(_):
        with Store(path) as store:
            return store.add_signal("couch", report())["evidence_score"]

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert list(workers.map(deliver, range(4))) == [65] * 4
    with Store(path) as store:
        assert len(store.get_issue("couch")["signal_ids"]) == 1
        assert len([e for e in store.events("couch") if e["event_type"] == "SIGNAL_LINKED"]) == 1


def test_poorer_location_evidence_removes_precision_points(tmp_path):
    with setup_store(tmp_path / "state.sqlite3") as store:
        store.add_signal("couch", report())
        result = store.record_geocode("couch", accuracy_m=31, provenance="seeded")
        assert result["evidence_score"] == 50
        assert result["score"]["components"]["precise_geocode"] == 0


def test_events_cannot_be_rewritten_or_deleted(tmp_path):
    path = tmp_path / "state.sqlite3"
    with setup_store(path):
        pass
    with sqlite3.connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE events SET event_type = 'FAKE_SUCCESS'")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM events")


def test_unlinked_receipt_trigger_invocation_reopen_and_link(tmp_path):
    path = tmp_path / "receipt.db"
    with Store(path) as store:
        result = receive(store)
        assert result.result.data.issue_id is None
        assert store.signal_receipt_actor("s1") == ACTOR.actor_id
        assert store.signal_receipt_actor("s1") != report().source_author_id
        event = store.get_event(result.result.event_ids[0])
        assert event.issue_id is None and event.signal_id == "s1"
    with Store(path) as store:
        assert store.get_request(result.id) == result
        assert store.pending_invocations()[0].id == "run-1"
        assert store.get_signal("s1") == report()
        assert store.signal_receipts_for_actor(ACTOR.actor_id)[0].signal_id == "s1"
        assert store.signal_receipts_for_actor("resident-1") == []
        store.create_issue("couch", "bulky_waste", "Demo")
        linked = store.link_signal("couch", "s1", expected_revision=0)
        assert linked["evidence_score"] == 50
        assert linked["state_revision"] == 1
        assert store.get_event(event.id) == event  # never rewrite original trigger provenance
        assert receive(store) == result
        assert len(store.pending_invocations()) == 1
        assert len(store.signal_events("s1")) == 2


@pytest.mark.parametrize("table", ["events", "signal_receipts", "invocations", "request_receipts"])
def test_receive_failure_rolls_back_every_record(tmp_path, table):
    path = tmp_path / "failure.db"
    with Store(path) as store:
        store.db.execute(f"CREATE TRIGGER injected BEFORE INSERT ON {table} "
                         "BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            receive(store)
        for name in ("signals", "events", "signal_receipts", "invocations", "request_receipts"):
            assert store.db.execute(f"SELECT count(*) FROM {name}").fetchone()[0] == 0
    with Store(path) as store:
        assert store.pending_invocations() == []


def test_failed_link_keeps_previously_accepted_receipt(tmp_path):
    with setup_store(tmp_path / "link.db") as store:
        result = receive(store)
        before = store.get_issue("couch")
        store.db.execute("CREATE TRIGGER injected BEFORE INSERT ON events "
                         "WHEN NEW.event_type='SIGNAL_LINKED' "
                         "BEGIN SELECT RAISE(ABORT,'link failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="link failure"):
            store.link_signal("couch", "s1")
        assert store.get_issue("couch") == before
        assert store.get_request(result.id) == result
        assert store.get_signal("s1") == report()
        assert len(store.signal_events("s1")) == 1


def test_intake_key_and_signal_identity_conflicts_do_not_add_effects(tmp_path):
    path = tmp_path / "retries.db"
    with Store(path) as store:
        original = receive(store)
        # Server-generated receipt time/next invocation ID do not alter a retry fingerprint.
        assert receive(store, replace(report(), received_at=datetime(2026, 9, 13, tzinfo=UTC)),
                       invocation_id="new-ignored-id") == original
        with pytest.raises(ValueError, match="payload conflict"):
            receive(store, report(text="changed"))
        with pytest.raises(ValueError, match="signal id payload conflict"):
            receive(store, report(text="changed"), key="different-key")
        assert receive(store, key="second-key", invocation_id="second-run") .invocation_id == "run-1"
        assert len(store.signal_events("s1")) == 1
        assert len(store.pending_invocations()) == 1


def test_concurrent_intake_and_competing_links_commit_once(tmp_path):
    path = tmp_path / "race.db"
    with Store(path) as store:
        store.create_issue("a", "litter", "A")
        store.create_issue("b", "litter", "B")

    def deliver(number):
        with Store(path) as store:
            return receive(store, invocation_id=f"run-{number}").id

    with ThreadPoolExecutor(max_workers=4) as workers:
        assert len(set(workers.map(deliver, range(8)))) == 1

    def link(issue):
        with Store(path) as store:
            try:
                store.link_signal(issue, "s1")
                return "linked"
            except ValueError:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(link, ("a", "b"))) == ["conflict", "linked"]
    with Store(path) as store:
        assert len(store.pending_invocations()) == 1
        assert store.db.execute("SELECT count(*) FROM issue_sources").fetchone()[0] == 1
        assert len(store.signal_events("s1")) == 2


def test_legacy_add_handles_unlinked_receipt_and_unchanged_retries(tmp_path):
    with setup_store(tmp_path / "old-api.db") as store:
        receipt = store.store_signal(report())
        assert store.add_signal("couch", report())["evidence_score"] == 65
        assert store.store_signal(report()) == receipt
        count = len(store.signal_events("s1"))
        store.db.execute("UPDATE issues SET status='RESOLVED' WHERE id='couch'")
        store.db.commit()
        assert store.link_signal("couch", "s1")["status"] == "RESOLVED"
        assert len(store.signal_events("s1")) == count


def test_transaction_cannot_escape_or_nest(tmp_path):
    with Store(tmp_path / "tx.db") as store:
        with (
            store.transaction() as tx,
            pytest.raises(RuntimeError, match="nested"),
            store.transaction(),
        ):
            pass
        with pytest.raises(RuntimeError, match="no longer active"):
            tx.insert_budget(c.BudgetRecord(id="d", initial_cents=50000, policy_version="v3"))
