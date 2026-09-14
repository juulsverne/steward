"""Financial boundaries exercised through real B5/B6/B7 producers; inspectors are offline fakes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from runtime_support import permit_context
from test_crew import crew_headers, dispatched_job, select_crew
from test_inspection import proof_ready_job, valid_findings
from test_inspection_repair import another_proof, inspect
from test_investigation import context
from test_investigation_repair import client_for, headers

from agent import operations as op
from agent.actors import AccessError
from agent.store import IdempotencyConflict, Store, StoreTransaction


def inspected_job(path, *, partial=False):
    job, proof = proof_ready_job(path)
    def findings(*_):
        result = valid_findings()
        result["findings"]["area_clear"] = not partial
        return result
    with client_for(path, completion_inspector=findings) as client:
        result = client.post(f"/api/jobs/{job}/inspect", headers=headers("inspection", 3),
            json={"submission_id": proof})
        assert result.status_code == 200, result.text
    return job, proof


def settle(client, job, proof, key="payment", revision=4):
    return client.post(f"/api/jobs/{job}/settle", headers=headers(key, revision),
        json={"submission_id": proof})


def assert_money(store, *, reserved, spent, available):
    balance = store.budget_availability("south_loop_demo")
    assert (balance.reserved_cents, balance.spent_cents, balance.available_cents) == (reserved, spent, available)


def test_real_partial_denial_is_durable_and_authenticates_b8(tmp_path):
    job, proof = inspected_job(tmp_path, partial=True)
    with client_for(tmp_path) as client:
        denied = settle(client, job, proof)
        assert denied.status_code == 403, denied.text
        body = denied.json()
        assert body["outcome"] == "DENIED" and "verification_below_threshold" in body["unmet"]
        assert "prerequisites_failed" not in body["unmet"]
    with Store(tmp_path / "b4.sqlite3") as store:
        verification = store.current_verification(job)
        event = store.get_event(body["event_ids"][0])
        assert event.event_type == "SETTLEMENT_DENIED"
        assert event.payload.record_id == verification.id
        assert event.payload.score_components == verification.components
        assert event.payload.gate_results == verification.prerequisites
        assert event.payload.unmet == ("area_clear",)
        assert event.payload.settlement.action_gate.allowed is False
        assert store.db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 0
        assert_money(store, reserved=7200, spent=0, available=42800)
    with client_for(tmp_path) as client:
        assert settle(client, job, proof).json() == body
        raised = client.post(f"/api/jobs/{job}/exceptions", headers=headers("real-exception", 4), json={
            "submission_id": proof, "verification_id": verification.id,
            "denial_event_id": event.id, "reason_code": "completion_incomplete"})
        assert raised.status_code == 202, raised.text


def test_payment_is_atomic_once_and_historical_close_survives_restart(tmp_path, monkeypatch):
    from agent import vision
    job, proof = inspected_job(tmp_path)
    with client_for(tmp_path) as client:
        paid = settle(client, job, proof)
        assert paid.status_code == 200, paid.text
    with Store(tmp_path / "b4.sqlite3") as store:
        saved_job = store.get_job(job)
        assert saved_job.status == "PAID" and saved_job.state_revision == 5
        assert store.get_issue_record("issue").status == "RESOLUTION_ACTIVE"
        payment = store.get_payment(paid.json()["data"]["record_id"])
        assert payment.amount_cents == 7200 and payment.submission_id == proof
        assert_money(store, reserved=0, spent=7200, available=42800)
        issue_revision = store.get_issue_record("issue").state_revision
    monkeypatch.setattr(vision, "TOOL_DESCRIPTION", "later request configuration after paid restart")
    with client_for(tmp_path) as client:
        assert settle(client, job, proof).json() == paid.json()
        assert settle(client, job, proof, key="second-payment", revision=5).status_code == 403
        closed = client.post("/api/issues/issue/close", headers=headers("close", issue_revision))
        assert closed.status_code == 200, closed.text
        assert client.post("/api/issues/issue/close", headers=headers("close", issue_revision)).json() == closed.json()
        assert client.post("/api/issues/issue/close", headers=headers("close-new-key", issue_revision + 1)).status_code == 200
    with Store(tmp_path / "b4.sqlite3") as store:
        issue = store.get_issue_record("issue")
        assert issue.status == "RESOLVED" and issue.resolved_at is not None
        assert issue.accepted_submission_id == proof and issue.state_revision == issue_revision + 1
        assert store.db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM ledger WHERE kind='CONSUME'").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM events WHERE event_type='ISSUE_RESOLVED'").fetchone()[0] == 1


def test_close_requires_paid_outcome(tmp_path):
    inspected_job(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        revision = store.get_issue_record("issue").state_revision
    with client_for(tmp_path) as client:
        result = client.post("/api/issues/issue/close", headers=headers("unpaid-close", revision))
        assert result.status_code == 403, result.text
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_issue_record("issue").resolved_at is None
        assert_money(store, reserved=7200, spent=0, available=42800)


def real_exception(path, *, chosen=False):
    """Unlike B8's isolated fixture, this consumes the actual B9 denial operation."""
    from test_operator import _operator_context
    job, proof = inspected_job(path, partial=True)
    with client_for(path) as client:
        denied = settle(client, job, proof)
        assert denied.status_code == 403
    with Store(path / "b4.sqlite3") as store:
        verification = store.current_verification(job)
        raised = op.escalate_to_operator(store, issue_id="issue", job_id=job, submission_id=proof,
            verification_id=verification.id, denial_event_id=denied.json()["event_ids"][0],
            reason_code="completion_incomplete", context=context("escalate_to_operator", "exception", 4))
        exception = raised.result.data.record_id
        decision = (op.request_completion(store, exception_id=exception, submission_id=proof,
            expected_job_revision=4, context=_operator_context("choice")).result.data if chosen else None)
    return job, proof, exception, decision


def test_actual_denial_rework_fresh_fixture_payment_and_close(tmp_path):
    from test_investigation import ORIGIN
    images = Path("data/images")
    job = dispatched_job(tmp_path)
    def partial(*_):
        result = valid_findings()
        result["findings"]["area_clear"] = False
        return result
    with client_for(tmp_path, completion_inspector=partial) as client:
        select_crew(client)
        assert client.post(f"/api/jobs/{job}/accept", headers=crew_headers("accept", 0)).status_code == 200
        assert client.post(f"/api/jobs/{job}/check-in", headers=crew_headers("check", 1), json={
            "latitude": 41.86, "longitude": -87.63, "accuracy_m": 5}).status_code == 200
        result = client.post(f"/api/jobs/{job}/proof", headers=crew_headers("partial-proof", 2), files={
            "before": ("before.jpg", (images / "before.jpg").read_bytes(), "image/jpeg"),
            "after": ("middle.jpg", (images / "middle.jpg").read_bytes(), "image/jpeg"),
            "metadata": (None, '{"before_observed_at":"2026-09-12T00:00:00Z","after_observed_at":"2026-09-13T00:00:00Z"}')})
        assert result.status_code == 202, result.text
        first = result.json()["data"]["record_id"]
        client.cookies.clear()
        assert client.post(f"/api/jobs/{job}/inspect", headers=headers("partial-inspect", 3),
            json={"submission_id": first}).status_code == 200
        denial = settle(client, job, first)
        assert denial.status_code == 403
    with Store(tmp_path / "b4.sqlite3") as store:
        original = store.get_job(job)
        reservation = store.reservation_for_job(job)
        verification = store.current_verification(job)
        before = store.get_submission(first).before_evidence_id
        first_cause = store.db.execute("SELECT id FROM invocations WHERE job_id=? AND trigger_type='PROOF_SUBMITTED'", (job,)).fetchone()[0]
    with client_for(tmp_path) as client:
        raised = client.post(f"/api/jobs/{job}/exceptions", headers=headers("raise", 4), json={
            "submission_id": first, "verification_id": verification.id,
            "denial_event_id": denial.json()["event_ids"][0], "reason_code": "completion_incomplete"})
        assert raised.status_code == 202, raised.text
        exception = raised.json()["data"]["record_id"]
        assert client.post("/api/demo/persona", headers=crew_headers("operator-persona", 0),
            json={"persona_id": "operator"}).status_code == 200
        choice = client.post(f"/api/exceptions/{exception}/request-completion",
            headers={"Origin": ORIGIN, "X-Steward-Request": "1", "Idempotency-Key": "choice", "X-Steward-Expected-Revision": "0"},
            json={"submission_id": first, "expected_job_revision": 4})
        assert choice.status_code == 202, choice.text
        client.cookies.clear()
        assert client.post(f"/api/operator-decisions/{choice.json()['data']['record_id']}/rework",
            headers=headers("rework", 4)).status_code == 200
    # Reopen between the saved choice/handling and fresh evidence; retained original before.
    with client_for(tmp_path, completion_inspector=valid_findings) as client:
        select_crew(client)
        fresh = client.post(f"/api/jobs/{job}/proof", headers=crew_headers("complete-proof", 5), files={
            "after": ("after.jpg", (images / "after.jpg").read_bytes(), "image/jpeg"),
            "metadata": (None, '{"after_observed_at":"2026-09-13T01:00:00Z"}')})
        assert fresh.status_code == 202, fresh.text
        proof = fresh.json()["data"]["record_id"]
        client.cookies.clear()
        inspected = client.post(f"/api/jobs/{job}/inspect", headers=headers("complete-inspect", 6), json={"submission_id": proof})
        assert inspected.status_code == 200 and inspected.json()["data"]["total"] == 100, inspected.text
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_submission(proof).before_evidence_id == before
        assert store.reservation_for_job(job) == reservation
        assert store.get_job(job).plan_id == original.plan_id
        assert_money(store, reserved=7200, spent=0, available=42800)
        wrong = context("settle", "bound-payment", 7).model_copy(update={"invocation_id": first_cause})
        with pytest.raises(AccessError):
            op.release_payment(store, job_id=job, submission_id=proof, context=wrong)
        latest_cause = store.db.execute("SELECT id FROM invocations WHERE job_id=? AND trigger_type='PROOF_SUBMITTED' ORDER BY rowid DESC", (job,)).fetchone()[0]
        bound = wrong.model_copy(update={"invocation_id": latest_cause})
        bound = permit_context(store, bound, "release_payment", job_id=job, submission_id=proof)
        paid = op.release_payment(store, job_id=job, submission_id=proof, context=bound)
        assert paid.result.outcome == "OK"
        with pytest.raises(AccessError):
            op.release_payment(store, job_id=job, submission_id=proof, context=wrong)
        issue = store.get_issue_record("issue")
        closed = op.close_issue(store, issue_id="issue", context=permit_context(store,
            context("close", "bound-close", issue.state_revision).model_copy(update={"invocation_id": latest_cause}),
            "close_issue", issue_id="issue"))
        assert closed.result.outcome == "OK"
    with client_for(tmp_path) as client:
        assert settle(client, job, first).json() == denial.json()
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_issue_record("issue").accepted_submission_id == proof
        assert store.get_exception(exception).status == "HANDLED"
        assert_money(store, reserved=0, spent=7200, available=42800)


@pytest.mark.parametrize("field,value", [("target_present_before", False), ("same_scene", False),
    ("target_present_before", None), ("same_scene", None), ("target_removed", None),
    ("area_clear", None), ("no_new_hazard", False)])
def test_unacceptable_or_unknown_findings_never_pay(tmp_path, field, value):
    job, proof = proof_ready_job(tmp_path)
    def findings(*_):
        result = valid_findings()
        result["findings"][field] = value
        return result
    inspect(tmp_path, job, proof, inspector=findings)
    with client_for(tmp_path) as client:
        result = settle(client, job, proof)
        assert result.status_code == 403, result.text
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.payment_for_job(job) is None
        assert_money(store, reserved=7200, spent=0, available=42800)


@pytest.mark.parametrize("checkin,metadata", [
    ({"latitude": 41.81, "longitude": -87.62, "accuracy_m": 5}, None),
    ({"latitude": 41.86, "longitude": -87.63}, {}),
    (None, {"before_observed_at": "2026-09-13T00:00:00Z", "after_observed_at": "2026-09-12T00:00:00Z"}),
])
def test_unknown_distant_gps_and_invalid_time_never_pay(tmp_path, checkin, metadata):
    job, proof = another_proof(tmp_path, checkin=checkin, metadata=metadata)
    inspect(tmp_path, job, proof)
    with client_for(tmp_path) as client:
        assert settle(client, job, proof).status_code == 403


def test_missing_inspection_and_reused_global_completion_never_pay(tmp_path):
    job, proof = proof_ready_job(tmp_path)
    with client_for(tmp_path) as client:
        missing = settle(client, job, proof, revision=3)
        assert missing.status_code == 403
        assert "current_verification_required" in missing.json()["unmet"]
    inspect(tmp_path, job, proof)
    second, second_proof = another_proof(tmp_path)
    inspect(tmp_path, second, second_proof, key="cached-second")
    with client_for(tmp_path) as client:
        denied = settle(client, second, second_proof, key="second-payment")
        assert denied.status_code == 403 and "prerequisites_failed" in denied.json()["unmet"]
    with Store(tmp_path / "b4.sqlite3") as store:
        assert sum(store.current_verification(second).components.model_dump().values()) == 100
        assert store.payment_for_job(second) is None


def test_changed_request_requires_reinspection_but_denial_replay_is_exact(tmp_path, monkeypatch):
    from agent import vision
    job, proof = inspected_job(tmp_path)
    monkeypatch.setattr(vision, "TOOL_DESCRIPTION", "changed interpretation before payment")
    with client_for(tmp_path) as client:
        denied = settle(client, job, proof)
        assert denied.status_code == 403 and "stale_completion_basis" in denied.json()["unmet"]
        assert settle(client, job, proof).json() == denied.json()
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.payment_for_job(job) is None


def test_financial_routes_reject_humans_extra_authority_and_foreign_actor(tmp_path):
    job, proof = inspected_job(tmp_path)
    with client_for(tmp_path) as client:
        for persona in ("resident-1", "operator", "crew-south_loop_services"):
            select_crew(client, persona)
            for path, body in ((f"/api/jobs/{job}/settle", {"submission_id": proof}),
                               (f"/api/jobs/{job}/cancel", {}), ("/api/issues/issue/close", {})):
                assert client.post(path, headers=crew_headers(f"human-{persona}", 4), json=body).status_code == 403
        client.cookies.clear()
        for key in ("amount_cents", "score", "accepted"):
            assert client.post(f"/api/jobs/{job}/settle", headers=headers(key, 4),
                json={"submission_id": proof, key: 1}).status_code == 422
        for path in (f"/api/jobs/{job}/cancel", "/api/issues/issue/close"):
            assert client.post(path, headers=headers("extra", 4), json={"amount_cents": 1}).status_code == 422
    ctx = context("settle", "foreign", 4)
    ctx = ctx.model_copy(update={"actor": ctx.actor.model_copy(update={"district_id": "foreign"})})
    with Store(tmp_path / "b4.sqlite3") as store, pytest.raises(AccessError):
        op.release_payment(store, job_id=job, submission_id=proof, context=ctx)


@pytest.mark.parametrize("same_key", [True, False])
def test_two_connections_pay_only_once(tmp_path, same_key):
    job, proof = inspected_job(tmp_path)
    barrier = Barrier(2)
    def pay(index):
        with Store(tmp_path / "b4.sqlite3") as store:
            barrier.wait(timeout=10)
            return op.release_payment(store, job_id=job, submission_id=proof,
                context=context("settle", "race" if same_key else f"race-{index}", 4))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(pay, (1, 2)))
    assert [r.result.outcome for r in results].count("OK") == (2 if same_key else 1)
    if same_key:
        assert results[0] == results[1]
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1
        assert_money(store, reserved=0, spent=7200, available=42800)


@pytest.mark.parametrize("stage", ["append_event", "insert_payment", "append_ledger", "replace_reservation", "replace_job", "save_request"])
def test_payment_failure_after_each_write_rolls_back_and_retries(tmp_path, monkeypatch, stage):
    job, proof = inspected_job(tmp_path)
    original = getattr(StoreTransaction, stage)
    def fail_after(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("injected interruption after write")
    with monkeypatch.context() as patch:
        patch.setattr(StoreTransaction, stage, fail_after)
        with Store(tmp_path / "b4.sqlite3") as store, pytest.raises(RuntimeError):
            op.release_payment(store, job_id=job, submission_id=proof, context=context("settle", "fault", 4))
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job).status == "VERIFIED"
        assert store.payment_for_job(job) is None
        assert store.db.execute("SELECT COUNT(*) FROM events WHERE event_type='SIMULATED_SETTLEMENT'").fetchone()[0] == 0
        assert_money(store, reserved=7200, spent=0, available=42800)
        assert op.release_payment(store, job_id=job, submission_id=proof, context=context("settle", "fault", 4)).result.outcome == "OK"


@pytest.mark.parametrize("damage", ["journal", "missing_reservation", "physical_source", "legacy_basis"])
def test_corrupt_or_unqualified_proof_rolls_back_without_denial_or_money(tmp_path, damage):
    job, proof = inspected_job(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        verification = store.current_verification(job)
        if damage in {"journal", "missing_reservation"}:
            store.db.execute("DROP TRIGGER ledger_no_delete")
            store.db.execute("DELETE FROM ledger WHERE job_id=?", (job,))
            if damage == "missing_reservation":
                store.db.execute("DELETE FROM reservations WHERE job_id=?", (job,))
        elif damage == "physical_source":
            attempt = store.get_completion_attempt(verification.attempt_id)
            changed = attempt.model_copy(update={"outcome": "ERROR"})
            store.db.execute("UPDATE completion_inspection_attempts SET record_json=? WHERE id=?", (changed.model_dump_json(), attempt.id))
        else:
            changed = verification.model_copy(update={"basis": None})
            store.db.execute("DROP TRIGGER verifications_no_update")
            store.db.execute("UPDATE verifications SET record_json=? WHERE id=?", (changed.model_dump_json(), verification.id))
        store.db.commit()
    with client_for(tmp_path) as client:
        denied = settle(client, job, proof)
        assert denied.status_code == (403 if damage == "legacy_basis" else 503), denied.text
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.payment_for_job(job) is None
        if damage != "legacy_basis":
            assert store.db.execute("SELECT COUNT(*) FROM request_receipts WHERE operation='settle'").fetchone()[0] == 0


def test_denied_close_replays_original_proof_cause_after_new_proof(tmp_path):
    from test_operator import _service_rework_context
    job, _proof, _exception, decision = real_exception(tmp_path, chosen=True)
    with Store(tmp_path / "b4.sqlite3") as store:
        invocation = store.db.execute("SELECT id FROM invocations WHERE job_id=? AND trigger_type='PROOF_SUBMITTED'", (job,)).fetchone()[0]
        revision = store.get_issue_record("issue").state_revision
        ctx = context("close", "denied-bound-close", revision).model_copy(update={"invocation_id": invocation})
        ctx = permit_context(store, ctx, "close_issue", issue_id="issue")
        denied = op.close_issue(store, issue_id="issue", context=ctx)
        assert denied.result.outcome == "DENIED"
        op.request_rework(store, decision_id=decision.record_id, context=_service_rework_context("rework"))
    with client_for(tmp_path) as client:
        select_crew(client)
        proof = client.post(f"/api/jobs/{job}/proof", headers=crew_headers("new-proof", 5), files={
            "after": ("after.jpg", Path("data/images/after.jpg").read_bytes(), "image/jpeg"),
            "metadata": (None, '{"after_observed_at":"2026-09-13T01:00:00Z"}')})
        assert proof.status_code == 202, proof.text
    with Store(tmp_path / "b4.sqlite3") as store:
        assert op.close_issue(store, issue_id="issue", context=ctx) == denied
        # A new request still cannot use this old proof cause against the newer proof.
        new_context = permit_context(store, ctx.model_copy(update={"runtime": None, "idempotency_key": "new-close"}),
                                     "close_issue", issue_id="issue")
        with pytest.raises(AccessError):
            op.close_issue(store, issue_id="issue", context=new_context)


def test_historical_close_rejects_missing_authoritative_physical_source(tmp_path):
    job, proof = inspected_job(tmp_path)
    with client_for(tmp_path) as client:
        assert settle(client, job, proof).status_code == 200
    with Store(tmp_path / "b4.sqlite3") as store:
        verification = store.get_verification(store.get_job(job).current_verification_id)
        # Deliberately inconsistent isolated storage: status alone cannot replace provenance.
        store.db.execute("DROP TRIGGER IF EXISTS completion_inspection_observations_no_delete")
        store.db.execute("DELETE FROM completion_inspection_observations WHERE attempt_id=?", (verification.attempt_id,))
        store.db.commit()
        revision = store.get_issue_record("issue").state_revision
    with client_for(tmp_path) as client:
        result = client.post("/api/issues/issue/close", headers=headers("invalid-close", revision))
        assert result.status_code == 503, result.text
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_issue_record("issue").resolved_at is None


def test_changed_payload_with_same_payment_key_conflicts(tmp_path):
    job, proof = inspected_job(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        ctx = context("settle", "immutable-request", 4)
        op.release_payment(store, job_id=job, submission_id=proof, context=ctx)
        with pytest.raises(IdempotencyConflict):
            op.release_payment(store, job_id=job, submission_id=proof,
                context=ctx.model_copy(update={"expected_revision": 5}))


def test_denied_close_replays_saved_contract_after_cancellation(tmp_path):
    job = dispatched_job(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        revision = store.get_issue_record("issue").state_revision
        ctx = context("close", "close-before-cancel", revision)
        denied = op.close_issue(store, issue_id="issue", context=ctx)
        assert denied.result.outcome == "DENIED"
        assert op.cancel_job(store, job_id=job, context=context("cancel", "cancel", 0)).result.outcome == "OK"
    with Store(tmp_path / "b4.sqlite3") as store:
        assert op.close_issue(store, issue_id="issue", context=ctx) == denied


@pytest.mark.parametrize("stage", ["append_event", "replace_issue", "save_request"])
def test_close_interruption_preserves_paid_outcome_and_retries_without_second_payment(tmp_path, monkeypatch, stage):
    job, proof = inspected_job(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        op.release_payment(store, job_id=job, submission_id=proof, context=context("settle", "paid", 4))
        ctx = context("close", "close-fault", store.get_issue_record("issue").state_revision)
    original = getattr(StoreTransaction, stage)
    def fail_after(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("interrupted closure")
    with monkeypatch.context() as patch:
        patch.setattr(StoreTransaction, stage, fail_after)
        with Store(tmp_path / "b4.sqlite3") as store, pytest.raises(RuntimeError):
            op.close_issue(store, issue_id="issue", context=ctx)
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_issue_record("issue").resolved_at is None
        assert store.get_job(job).status == "PAID"
        assert_money(store, reserved=0, spent=7200, available=42800)
        assert op.close_issue(store, issue_id="issue", context=ctx).result.outcome == "OK"
        assert store.db.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1


def test_new_failed_reinspection_cannot_pay_from_old_success(tmp_path, monkeypatch):
    from agent.vision import VisionRequestBasis
    job, proof = inspected_job(tmp_path)
    monkeypatch.setattr(op, "capture_request_basis", lambda: VisionRequestBasis(
        model_id="new-frozen-test-model", region="us-west-2", profile="test"))
    def unknown(*_):
        result = valid_findings()
        result["findings"]["same_scene"] = None
        return result
    inspect(tmp_path, job, proof, key="new-interpretation", revision=4, inspector=unknown)
    with client_for(tmp_path) as client:
        stale = settle(client, job, proof, revision=4)
        assert stale.status_code == 403 and "stale_job_revision" in stale.json()["unmet"]
        current = settle(client, job, proof, key="current", revision=5)
        assert current.status_code == 403 and "prerequisites_failed" in current.json()["unmet"]
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.payment_for_job(job) is None


def test_changed_allocation_blocks_payment_but_does_not_rewrite_paid_history(tmp_path):
    import json

    from agent.policy import DEFAULT_POLICY_PATH
    job, proof = inspected_job(tmp_path)
    policy = json.loads(DEFAULT_POLICY_PATH.read_text())
    # The policy parser intentionally locks its version. Its allocation remains a
    # valid configurable input, but must not replace this job's saved money notebook.
    policy["budget_cents"] = 60000
    changed_path = tmp_path / "later-policy.json"
    changed_path.write_text(json.dumps(policy))
    with Store(tmp_path / "b4.sqlite3") as store:
        with pytest.raises(ValueError, match="budget"):
            op.release_payment(store, job_id=job, submission_id=proof, context=context("settle", "changed", 4), policy_path=changed_path)
        paid = op.release_payment(store, job_id=job, submission_id=proof, context=context("settle", "original", 4))
        assert paid.result.outcome == "OK"
        result = op.close_issue(store, issue_id="issue", policy_path=changed_path,
            context=context("close", "historical-policy", store.get_issue_record("issue").state_revision))
        assert result.result.outcome == "OK"


def test_stale_actual_settlement_denial_cannot_become_completion_exception(tmp_path):
    job, proof = inspected_job(tmp_path, partial=True)
    with client_for(tmp_path) as client:
        stale = settle(client, job, proof, revision=3)
        assert stale.status_code == 403 and "stale_job_revision" in stale.json()["unmet"]
    with Store(tmp_path / "b4.sqlite3") as store:
        verification = store.current_verification(job)
    with client_for(tmp_path) as client:
        raised = client.post(f"/api/jobs/{job}/exceptions", headers=headers("stale-denial", 4), json={
            "submission_id": proof, "verification_id": verification.id,
            "denial_event_id": stale.json()["event_ids"][0], "reason_code": "completion_incomplete"})
        assert raised.status_code == 422, raised.text
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.open_completion_exception(job) is None
