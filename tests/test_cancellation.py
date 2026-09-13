from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from test_crew import dispatched_job
from test_investigation import context
from test_investigation_repair import client_for, headers
from test_operator import _service_rework_context
from test_settlement import assert_money, inspected_job, real_exception, settle

from agent import operations as op
from agent.store import RevisionConflict, Store, StoreTransaction


def test_unpaid_cancellation_releases_once_and_never_resolves(tmp_path):
    job = dispatched_job(tmp_path)
    with client_for(tmp_path) as client:
        cancelled = client.post(f"/api/jobs/{job}/cancel", headers=headers("cancel", 0))
        assert cancelled.status_code == 200, cancelled.text
    with client_for(tmp_path) as client:
        assert client.post(f"/api/jobs/{job}/cancel", headers=headers("cancel", 0)).json() == cancelled.json()
        second = client.post(f"/api/jobs/{job}/cancel", headers=headers("cancel-again", 1))
        assert second.status_code == 403, second.text
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job).status == "CANCELLED"
        assert store.get_issue_record("issue").status == "RESOLUTION_ACTIVE"
        assert store.get_issue_record("issue").resolved_at is None
        assert_money(store, reserved=0, spent=0, available=50000)
        assert store.db.execute("SELECT COUNT(*) FROM ledger WHERE kind='RELEASE'").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0


@pytest.mark.parametrize("chosen", [False, True])
def test_cancellation_invalidates_pending_choice_without_pretending_handled(tmp_path, chosen):
    job, _proof, exception, decision = real_exception(tmp_path, chosen=chosen)
    with client_for(tmp_path) as client:
        cancelled = client.post(f"/api/jobs/{job}/cancel", headers=headers("cancel", 4))
        assert cancelled.status_code == 200, cancelled.text
    with Store(tmp_path / "b4.sqlite3") as store:
        saved = store.get_exception(exception)
        assert saved.status == "CANCELLED" and saved.handled_at is None
        assert saved.cancellation_event_id == cancelled.json()["event_ids"][0]
        assert store.get_event(saved.cancellation_event_id).timestamp == saved.cancelled_at
        assert_money(store, reserved=0, spent=0, available=50000)
        if chosen:
            assert store.get_operator_decision(decision.record_id).handled_at is None
            with pytest.raises(RevisionConflict):
                op.request_rework(store, decision_id=decision.record_id, context=_service_rework_context("late-rework"))
    with client_for(tmp_path) as client:
        detail = client.get(f"/api/exceptions/{exception}", headers=headers("detail"))
        assert detail.status_code == 200 and detail.json()["data"]["allowed_next"] == []
        assert detail.json()["data"]["total"] == 90


def test_paid_job_never_releases_funds(tmp_path):
    job, proof = inspected_job(tmp_path)
    with client_for(tmp_path) as client:
        assert settle(client, job, proof).status_code == 200
        denied = client.post(f"/api/jobs/{job}/cancel", headers=headers("too-late", 5))
        assert denied.status_code == 403 and "already_paid" in denied.json()["unmet"]
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job).status == "PAID"
        assert_money(store, reserved=0, spent=7200, available=42800)


def test_payment_cancellation_race_has_exactly_one_terminal_movement(tmp_path):
    job, proof = inspected_job(tmp_path)
    barrier = Barrier(2)
    def run(action):
        with Store(tmp_path / "b4.sqlite3") as store:
            barrier.wait(timeout=10)
            if action == "settle":
                return op.release_payment(store, job_id=job, submission_id=proof, context=context(action, action, 4))
            return op.cancel_job(store, job_id=job, context=context(action, action, 4))
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, ("settle", "cancel")))
    assert [r.result.outcome for r in outcomes].count("OK") == 1
    with Store(tmp_path / "b4.sqlite3") as store:
        status = store.get_job(job).status
        assert status in {"PAID", "CANCELLED"}
        assert store.db.execute("SELECT COUNT(*) FROM ledger WHERE kind IN ('CONSUME','RELEASE')").fetchone()[0] == 1
        assert_money(store, reserved=0, spent=7200 if status == "PAID" else 0,
            available=42800 if status == "PAID" else 50000)


def test_cancellation_rework_race_preserves_real_choice_history(tmp_path):
    job, _proof, exception, decision = real_exception(tmp_path, chosen=True)
    barrier = Barrier(2)
    def run(action):
        with Store(tmp_path / "b4.sqlite3") as store:
            barrier.wait(timeout=10)
            if action == "cancel":
                return op.cancel_job(store, job_id=job, context=context("cancel", "racing-cancel", 4)).result.outcome
            try:
                return op.request_rework(store, decision_id=decision.record_id,
                    context=_service_rework_context("racing-rework").model_copy(
                        update={"invocation_id": decision.invocation_id})).result.outcome
            except RevisionConflict:
                return "DENIED"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, ("cancel", "rework"))).count("OK") == 1
    with Store(tmp_path / "b4.sqlite3") as store:
        cancelled = store.get_job(job).status == "CANCELLED"
        saved = store.get_exception(exception)
        assert saved.status == ("CANCELLED" if cancelled else "HANDLED")
        assert (store.get_operator_decision(decision.record_id).handled_at is None) == cancelled
        if not cancelled:
            applied = op.cancel_job(store, job_id=job, context=context("cancel", "retry-cancel", 5))
            assert applied.result.outcome == "OK"
            assert store.get_exception(exception) == saved
        assert_money(store, reserved=0, spent=0, available=50000)


@pytest.mark.parametrize("stage", ["append_event", "append_ledger", "replace_reservation", "replace_job", "replace_exception", "save_request"])
def test_cancellation_failure_rolls_back_money_exception_and_receipt(tmp_path, monkeypatch, stage):
    job, _proof, exception, decision = real_exception(tmp_path, chosen=True)
    original = getattr(StoreTransaction, stage)
    def fail_after(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("interrupted cancellation write")
    with monkeypatch.context() as patch:
        patch.setattr(StoreTransaction, stage, fail_after)
        with Store(tmp_path / "b4.sqlite3") as store, pytest.raises(RuntimeError):
            op.cancel_job(store, job_id=job, context=context("cancel", "fault", 4))
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job).status == "PROOF_SUBMITTED"
        assert store.get_exception(exception).status == "DECIDED"
        assert store.get_operator_decision(decision.record_id).handled_at is None
        assert store.db.execute("SELECT COUNT(*) FROM events WHERE event_type='JOB_CANCELLED'").fetchone()[0] == 0
        assert_money(store, reserved=7200, spent=0, available=42800)
        assert op.cancel_job(store, job_id=job, context=context("cancel", "fault", 4)).result.outcome == "OK"


@pytest.mark.parametrize("same_key", [False, True])
def test_two_cancellations_release_once(tmp_path, same_key):
    job = dispatched_job(tmp_path)
    barrier = Barrier(2)
    def cancel(index):
        with Store(tmp_path / "b4.sqlite3") as store:
            barrier.wait(timeout=10)
            return op.cancel_job(store, job_id=job,
                context=context("cancel", "same" if same_key else f"cancel-{index}", 0))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(cancel, (1, 2)))
    assert [r.result.outcome for r in results].count("OK") == (2 if same_key else 1)
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.db.execute("SELECT COUNT(*) FROM ledger WHERE kind='RELEASE'").fetchone()[0] == 1
        assert_money(store, reserved=0, spent=0, available=50000)


@pytest.mark.parametrize("action", ["cancel", "close"])
def test_financial_bodyless_routes_reject_unframed_streams_before_mutation(tmp_path, action):
    import asyncio
    from urllib.parse import urlsplit

    from test_investigation import ORIGIN
    job = dispatched_job(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        revision = 0 if action == "cancel" else store.get_issue_record("issue").state_revision
        original_job = store.get_job(job)
        original_issue = store.get_issue_record("issue")
        original_events = store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    path = f"/api/jobs/{job}/cancel" if action == "cancel" else "/api/issues/issue/close"
    with client_for(tmp_path) as client:
        # A direct ASGI scope avoids HTTP clients repairing absent/zero framing.
        async def raw_request(framing):
            sent = []
            consumed = False
            async def receive():
                nonlocal consumed
                assert not consumed, "reject the first nonempty chunk without reading the rest"
                consumed = True
                return {"type": "http.request", "body": b'{"amount_cents":1}', "more_body": True}
            async def send(message):
                sent.append(message)
            raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers(f"raw-{action}", revision).items()]
            host = urlsplit(ORIGIN).netloc.encode()
            scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                "http_version": "1.1", "method": "POST", "scheme": "http", "path": path,
                "raw_path": path.encode(), "query_string": b"", "root_path": "",
                "headers": [(b"host", host), *raw_headers, *framing], "client": ("127.0.0.1", 1),
                "server": ("testserver", 80)}
            await client.app(scope, receive, send)
            return next(message["status"] for message in sent if message["type"] == "http.response.start")
        for framing, status in (([], 422), ([(b"content-length", b"0")], 422),
                                ([(b"content-length", b"0"), (b"content-length", b"0")], 400)):
            assert asyncio.run(raw_request(framing)) == status
        for body in ({}, {"amount_cents": 1}):
            response = client.post(path, headers=headers("json-body", revision), json=body)
            assert response.status_code == 422, response.text
        with Store(tmp_path / "b4.sqlite3") as store:
            assert store.get_job(job) == original_job
            assert store.get_issue_record("issue") == original_issue
            assert store.db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == original_events
            assert store.db.execute("SELECT COUNT(*) FROM request_receipts WHERE operation=?", (action,)).fetchone()[0] == 0
            assert_money(store, reserved=7200, spent=0, available=42800)
        accepted_request = client.post(path, headers=headers("empty-body", revision))
        assert accepted_request.status_code == (200 if action == "cancel" else 403), accepted_request.text
        assert accepted_request.json()["event_ids"]  # empty body reaches the actual operation
