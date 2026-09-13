"""Mutation-boundary regressions retained from independent B8 review."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_crew import crew_headers, select_crew
from test_dispatch import create_plan, dispatch
from test_inspection import picture, proof_ready_job, valid_findings
from test_investigation import context
from test_investigation_repair import client_for, headers
from test_operator import (
    _exhausted_budget_denial,
    _operator_context,
    _pending_partial_exception,
    _service_rework_context,
    _synthetic_settlement_denial,
)

from agent import contracts as c
from agent import investigation as inv
from agent import operations as op
from agent import vision
from agent.actors import AccessError
from agent.store import RevisionConflict, Store


def chosen(path):
    job, proof, exception = _pending_partial_exception(path)
    with Store(path / "b4.sqlite3") as store:
        decision = op.request_completion(store, exception_id=exception, submission_id=proof,
            expected_job_revision=4, context=_operator_context("choice")).result.data
    return job, proof, exception, decision


def partial_before_exception(path):
    job, proof = proof_ready_job(path)
    def partial(*_):
        answer = valid_findings()
        answer["findings"]["area_clear"] = False
        return answer
    with client_for(path, completion_inspector=partial) as client:
        response = client.post(f"/api/jobs/{job}/inspect", headers=headers("partial", 3),
            json={"submission_id": proof})
        assert response.status_code == 200, response.text
    verification, denial = _synthetic_settlement_denial(path, job)
    return job, proof, verification, denial


def test_rework_rejects_actual_b6_cause_instead_of_saved_operator_cause(tmp_path):
    job, _proof, _exception, decision = chosen(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        wrong = store.db.execute("SELECT id FROM invocations WHERE job_id=? AND trigger_type='PROOF_SUBMITTED'",
            (job,)).fetchone()[0]
        ctx = _service_rework_context("wrong-cause").model_copy(update={"invocation_id": wrong})
        with pytest.raises((ValueError, RevisionConflict)):
            op.request_rework(store, decision_id=decision.record_id, context=ctx)


def test_rework_rejects_damaged_reservation_journal(tmp_path):
    job, _proof, _exception, decision = chosen(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        store.db.execute("DROP TRIGGER ledger_no_delete")
        store.db.execute("DELETE FROM ledger WHERE job_id=?", (job,))
        store.db.commit()
        with pytest.raises(ValueError):
            store.budget_availability("south_loop_demo")
        with pytest.raises((ValueError, RevisionConflict)):
            op.request_rework(store, decision_id=decision.record_id,
                context=_service_rework_context("broken-journal"))


def test_escalation_rejects_obsolete_physical_request_basis(tmp_path, monkeypatch):
    job, proof, verification, denial = partial_before_exception(tmp_path)
    monkeypatch.setattr(vision, "TOOL_DESCRIPTION", "different configured interpretation")
    with client_for(tmp_path) as client:
        response = client.post(f"/api/jobs/{job}/exceptions", headers=headers("stale-basis", 4), json={
            "submission_id": proof, "verification_id": verification.id,
            "denial_event_id": denial.id, "reason_code": "completion_incomplete"})
    assert response.status_code in (409, 422), response.text


def test_rework_rejects_obsolete_physical_request_basis(tmp_path, monkeypatch):
    _job, _proof, _exception, decision = chosen(tmp_path)
    monkeypatch.setattr(vision, "TOOL_DESCRIPTION", "different configured interpretation")
    with Store(tmp_path / "b4.sqlite3") as store, pytest.raises((ValueError, RevisionConflict)):
        op.request_rework(store, decision_id=decision.record_id,
            context=_service_rework_context("stale-rework"))


def test_operator_decided_detail_has_no_service_rework_action(tmp_path):
    _job, _proof, exception, _decision = chosen(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        detail = op.exception_detail(store, exception_id=exception, actor=_operator_context("read").actor)
        assert detail.allowed_next == (), detail.model_dump()


def test_pending_detail_removes_action_after_job_state_changes(tmp_path):
    job, _proof, exception = _pending_partial_exception(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        saved = store.get_job(job)
        with store.transaction() as tx:
            tx.replace_job(saved.model_copy(update={"status": "REWORK_REQUIRED", "state_revision": 5}), 4)
        detail = op.exception_detail(store, exception_id=exception, actor=_operator_context("read").actor)
        assert detail.allowed_next == (), detail.model_dump()


def test_duplicate_exception_receipt_retains_saved_event_ids(tmp_path):
    job, proof, exception = _pending_partial_exception(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        saved = store.get_exception(exception)
        result = op.escalate_to_operator(store, issue_id=saved.issue_id, job_id=job,
            submission_id=proof, verification_id=saved.verification_id, denial_event_id=saved.denial_event_id,
            reason_code=saved.reason_code, context=context("escalate_to_operator", "duplicate", 4))
        assert result.result.event_ids, result.model_dump()
        assert result.result.evidence_ids == (saved.before_evidence_id, saved.after_evidence_id)


def test_changed_but_still_short_budget_preserves_original_denial(tmp_path):
    revision, denial_id = _exhausted_budget_denial(tmp_path, "review")
    plan, other_revision = create_plan(tmp_path, "later-small-job", objects=0)
    with client_for(tmp_path) as client:
        result = dispatch(client, plan, other_revision, key="later-reservation")
        assert result.status_code == 201, result.text
        result = client.post("/api/issues/issue/exceptions", headers=headers("still-short", revision), json={
            "kind": "budget", "reason_code": "insufficient_budget", "denial_event_id": denial_id})
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.budget_availability("south_loop_demo").available_cents < 7200
    assert result.status_code == 202, result.text


def test_historical_detail_and_saved_job_district_guard(tmp_path):
    job, _proof, exception, decision = chosen(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        op.request_rework(store, decision_id=decision.record_id, context=_service_rework_context("valid"))
        with pytest.raises(ValueError):
            store.current_verification(job)
        detail = op.exception_detail(store, exception_id=exception, actor=_operator_context("read").actor)
        assert detail.status == "HANDLED" and detail.total == 90 and detail.job_revision == 5
        assert detail.invocation_id == decision.invocation_id
        plan = store.get_plan(store.get_job(job).plan_id)
        store.db.execute("DROP TRIGGER plans_no_update")
        foreign = plan.model_copy(update={"district_id": "foreign"})
        store.db.execute("UPDATE plans SET record_json=?,district_id=? WHERE id=?",
            (foreign.model_dump_json(), "foreign", plan.id))
        store.db.commit()
        with pytest.raises(AccessError):
            op.exception_detail(store, exception_id=exception, actor=_operator_context("read").actor)


def test_prejob_authority_does_not_hide_an_existing_active_job(tmp_path):
    plan, revision = create_plan(tmp_path)
    with client_for(tmp_path) as client:
        dispatched = dispatch(client, plan, revision)
        assert dispatched.status_code == 201
    with Store(tmp_path / "b4.sqlite3") as store:
        issue = store.get_issue_record("issue")
        current = store.current_issue_facts("issue").jurisdiction
        fact = current.model_copy(update={"id": "new-city-responsibility", "responsibility": "city",
            "source_issue_revision": issue.state_revision})
        inv.save_jurisdiction(store, fact,
            context=context("jurisdiction", "updated-authority", issue.state_revision))
        revision = store.get_issue_record("issue").state_revision
        assert store.active_job_for_issue("issue") is not None
    with client_for(tmp_path) as client:
        response = client.post("/api/issues/issue/exceptions", headers=headers("authority-with-job", revision),
            json={"kind": "authority", "reason_code": "city_responsibility"})
    assert response.status_code in (409, 422), response.text


def assert_choice_waiting(store, job_id, exception_id, decision_id):
    assert store.get_job(job_id).state_revision == 4
    assert store.get_exception(exception_id).status == "DECIDED"
    assert store.get_operator_decision(decision_id).handled_at is None
    assert store.open_completion_exception(job_id).id == exception_id


def test_exact_operator_cause_replays_after_restart_but_altered_trigger_is_rejected(tmp_path, monkeypatch):
    job, _proof, exception, decision = chosen(tmp_path)
    ctx = _service_rework_context("bound-rework").model_copy(update={"invocation_id": decision.invocation_id})
    with Store(tmp_path / "b4.sqlite3") as store:
        applied = op.request_rework(store, decision_id=decision.record_id, context=ctx)
        assert applied.invocation_id == decision.invocation_id
        saved_job = store.get_job(job)
    monkeypatch.setattr(vision, "TOOL_DESCRIPTION", "later interpretation version")
    with Store(tmp_path / "b4.sqlite3") as store:
        assert op.request_rework(store, decision_id=decision.record_id, context=ctx) == applied
        assert store.get_job(job) == saved_job
        assert op.exception_detail(store, exception_id=exception,
            actor=_operator_context("read").actor).total == 90
        # Isolated damaged audit: replay must authorize its saved cause before lookup.
        trigger = store.get_event(store.get_invocation(decision.invocation_id).trigger_event_id)
        store.db.execute("DROP TRIGGER events_no_update")
        store.db.execute("UPDATE events SET actor_id=?,actor_json=? WHERE id=?",
            (ctx.actor.actor_id, ctx.actor.model_dump_json(), trigger.id))
        store.db.commit()
        with pytest.raises(ValueError, match="trigger"):
            op.request_rework(store, decision_id=decision.record_id, context=ctx)


def test_later_real_operator_choice_cannot_replay_an_earlier_choice(tmp_path):
    job, _proof, _exception, first = chosen(tmp_path)
    first_ctx = _service_rework_context("first-bound").model_copy(update={"invocation_id": first.invocation_id})
    with Store(tmp_path / "b4.sqlite3") as store:
        op.request_rework(store, decision_id=first.record_id, context=first_ctx)
    with client_for(tmp_path, completion_inspector=valid_findings) as client:
        select_crew(client)
        submitted = client.post(f"/api/jobs/{job}/proof", headers=crew_headers("second-proof", 5), files={
            "after": ("fresh-after.jpg", picture("blue"), "image/jpeg"),
            "metadata": (None, '{"after_observed_at":"2026-09-13T01:00:00+00:00"}')})
        assert submitted.status_code == 202, submitted.text
        proof = submitted.json()["data"]["record_id"]
        client.cookies.clear()
        inspected = client.post(f"/api/jobs/{job}/inspect", headers=headers("second-inspect", 6),
            json={"submission_id": proof})
        assert inspected.status_code == 200, inspected.text
        # Uniform test images share a dHash; this is a real required reuse denial.
        assert "image_reuse" in inspected.json()["unmet"]
    verification, denial = _synthetic_settlement_denial(tmp_path, job)
    with Store(tmp_path / "b4.sqlite3") as store:
        raised = op.escalate_to_operator(store, issue_id="issue", job_id=job, submission_id=proof,
            verification_id=verification.id, denial_event_id=denial.id, reason_code="reused-proof",
            context=context("escalate_to_operator", "second-exception", 7)).result.data
        second = op.request_completion(store, exception_id=raised.record_id, submission_id=proof,
            expected_job_revision=7, context=_operator_context("second-choice")).result.data
        wrong = first_ctx.model_copy(update={"invocation_id": second.invocation_id})
        with pytest.raises(ValueError, match="exact saved operator"):
            op.request_rework(store, decision_id=first.record_id, context=wrong)
        assert store.get_operator_decision(second.record_id).handled_at is None
        assert store.get_job(job).state_revision == 7


@pytest.mark.parametrize("damage", ("reservation_amount", "payment_without_consume", "terminal_release"))
def test_rework_rejects_inconsistent_money_without_handling_choice(tmp_path, damage):
    job, proof, exception, decision = chosen(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        reservation = store.reservation_for_job(job)
        if damage == "reservation_amount":
            changed = reservation.model_copy(update={"amount_cents": 1})
            store.db.execute("UPDATE reservations SET record_json=?,amount_cents=? WHERE id=?",
                (changed.model_dump_json(), 1, reservation.id))
            store.db.commit()
        else:
            # Deliberate inconsistent storage primitives, not B9 payment/cancellation operations.
            with store.transaction() as tx:
                if damage == "payment_without_consume":
                    tx.insert_payment(c.PaymentRecord(id=str(uuid4()), issue_id="issue", job_id=job,
                        reservation_id=reservation.id, submission_id=proof,
                        verification_id=store.get_exception(exception).verification_id,
                        amount_cents=7200, idempotency_key="synthetic-damaged-payment", created_at=datetime.now(UTC)))
                else:
                    reserve = store.ledger_for_reservation(reservation.id)[0]
                    tx.append_ledger(c.LedgerEntry(id=str(uuid4()), budget_id=reservation.budget_id,
                        job_id=job, reservation_id=reservation.id, kind="RELEASE", amount_cents=7200,
                        event_id=reserve.event_id, created_at=datetime.now(UTC)))
        with pytest.raises((ValueError, RevisionConflict)):
            op.request_rework(store, decision_id=decision.record_id, context=_service_rework_context("damaged"))
        assert_choice_waiting(store, job, exception, decision.record_id)


def test_stale_interpretation_blocks_choice_but_preserves_history_and_exact_escalation_replay(tmp_path, monkeypatch):
    job, proof, exception = _pending_partial_exception(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        saved = store.get_exception(exception)
        first = store.exception_result_receipt(exception)
    monkeypatch.setattr(vision, "TOOL_DESCRIPTION", "obsolete pending interpretation")
    with Store(tmp_path / "b4.sqlite3") as store:
        with pytest.raises(RevisionConflict):
            op.request_completion(store, exception_id=exception, submission_id=proof,
                expected_job_revision=4, context=_operator_context("stale-choice"))
        detail = op.exception_detail(store, exception_id=exception, actor=_operator_context("read").actor)
        assert detail.total == 90 and detail.allowed_next == ()
        assert store.operator_decision_for_exception(exception) is None
        replay = op.escalate_to_operator(store, issue_id="issue", job_id=job, submission_id=proof,
            verification_id=saved.verification_id, denial_event_id=saved.denial_event_id,
            reason_code=saved.reason_code, context=context("escalate_to_operator", "setup-exception", 4))
        assert replay == first


@pytest.mark.parametrize("damage", ("missing_basis", "changed_hash", "changed_scope", "invented_gates", "missing_source"))
def test_legacy_or_inconsistent_current_verification_cannot_authorize_choice(tmp_path, damage):
    job, proof, exception = _pending_partial_exception(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        verification = store.current_verification(job)
        if damage == "missing_basis":
            updates = {"basis": None}
        elif damage == "changed_hash":
            updates = {"basis": verification.basis.model_copy(update={"after_sha256": "f" * 64})}
        elif damage == "changed_scope":
            updates = {"basis": verification.basis.model_copy(update={"scope": "another scope"})}
        elif damage == "invented_gates":
            updates = {"prerequisites": (c.GateRecord(name="untrusted_gate", allowed=False),)}
        else:
            updates = {"attempt_id": None}
        damaged = verification.model_copy(update=updates)
        store.db.execute("DROP TRIGGER verifications_no_update")
        store.db.execute("UPDATE verifications SET record_json=? WHERE id=?",
            (damaged.model_dump_json(), verification.id))
        store.db.commit()
        with pytest.raises((ValueError, RevisionConflict)):
            op.request_completion(store, exception_id=exception, submission_id=proof,
                expected_job_revision=4, context=_operator_context("inconsistent-choice"))
        assert store.get_exception(exception).status == "PENDING"
        assert store.operator_decision_for_exception(exception) is None


def test_prejob_duplicate_reuses_original_event_and_requirements_after_restart(tmp_path):
    from test_dispatch import prepare

    _classified, revision = prepare(tmp_path, authority="city")
    ctx = context("escalate_to_operator", "authority-first", revision)
    with Store(tmp_path / "b4.sqlite3") as store:
        original = op.escalate_to_operator(store, issue_id="issue", kind="authority",
            reason_code="city_responsibility", context=ctx)
    with Store(tmp_path / "b4.sqlite3") as store:
        duplicate = op.escalate_to_operator(store, issue_id="issue", kind="authority",
            reason_code="city_responsibility", context=ctx.model_copy(update={"idempotency_key": "authority-second"}))
        assert duplicate.result == original.result
        assert duplicate.result.event_ids and duplicate.result.unmet == ("city_responsibility",)
        assert store.db.execute("SELECT COUNT(*) FROM events WHERE event_type='EXCEPTION_RAISED'").fetchone()[0] == 1


@pytest.mark.parametrize("status", ("RESOLVED", "INVALID", "DUPLICATE", "RESOLUTION_ACTIVE"))
def test_prejob_authority_rejects_ineligible_issue_lifecycle(tmp_path, status):
    from test_dispatch import prepare

    _classified, revision = prepare(tmp_path, authority="city")
    with Store(tmp_path / "b4.sqlite3") as store:
        issue = store.get_issue_record("issue")
        with store.transaction() as tx:
            tx.replace_issue(issue.model_copy(update={"status": status, "state_revision": revision + 1}), revision)
        with pytest.raises(RevisionConflict):
            op.escalate_to_operator(store, issue_id="issue", kind="authority", reason_code="city_responsibility",
                context=context("escalate_to_operator", "terminal-authority", revision + 1))
        assert store.exceptions_for_issue("issue") == []
