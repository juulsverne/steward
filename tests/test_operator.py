from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_crew import crew_headers, select_crew
from test_dispatch import create_plan, dispatch, prepare
from test_inspection import picture, proof_ready_job, valid_findings
from test_investigation import ORIGIN, context
from test_investigation_repair import client_for, headers

from agent import contracts as c
from agent import investigation as inv
from agent.actors import Action
from agent.operations import request_completion, request_rework
from agent.store import Store, StoreTransaction


def test_pending_entity_result_keeps_old_entity_shape_and_requires_invocation_id():
    old = c.EntityResult(record_id="old")
    assert old.model_dump() == {"record_id": "old", "state_revision": None}
    pending = c.PendingEntityResult(record_id="decision", invocation_id="invoke")
    assert pending.invocation_id == "invoke"
    assert pending.state_revision is None


def test_operator_routes_publish_header_and_exact_body_contract(tmp_path):
    with client_for(tmp_path) as client:
        paths = client.get("/openapi.json").json()["paths"]
    assert "/api/jobs/{job_id}/exceptions" in paths
    assert "/api/issues/{issue_id}/exceptions" in paths
    assert "/api/exceptions/{exception_id}/request-completion" in paths
    assert "/api/operator-decisions/{decision_id}/rework" in paths
    operator = paths["/api/exceptions/{exception_id}/request-completion"]["post"]
    assert {item["name"] for item in operator["parameters"] if item["in"] == "header" and item["required"]} == {
        "Idempotency-Key", "X-Steward-Expected-Revision"
    }
    assert "expected_exception_revision" not in str(operator["requestBody"])
    assert "expected_job_revision" in str(operator["requestBody"])


def _synthetic_settlement_denial(path, job_id, *, score_components=None, event_type="SETTLEMENT_DENIED"):
    """B8's explicit stand-in until B9 writes the real settlement endpoint."""
    with Store(path / "b4.sqlite3") as store, store.transaction() as tx:
        job = store.get_job(job_id)
        verification = store.current_verification(job_id)
        assert verification is not None
        plan = store.get_plan(job.plan_id)
        actor = c.ActorContext(actor_id="steward-service", actor_type="service", label="Steward",
            district_id="south_loop_demo")
        event = tx.append_event(c.NewEvent(issue_id=job.issue_id, job_id=job.id,
            event_type=event_type, timestamp=datetime.now(UTC), actor=actor,
            state_revision=job.state_revision, policy_version=plan.policy_version,
            payload=c.EventFacts(summary="Synthetic B8 test denial; B9 owns real settlement.", outcome="DENIED",
                record_id=verification.id, submission_id=verification.submission_id,
                unmet=verification.unmet, score_components=score_components or verification.components,
                gate_results=verification.prerequisites, simulated=True)))
        receipt = c.RequestReceipt(id=str(uuid4()), operation=Action.SETTLE.value, actor_id=actor.actor_id,
            idempotency_key=f"synthetic-b8-settlement-{uuid4()}", request_sha256="d" * 64,
            issue_id=job.issue_id, job_id=job.id, created_at=datetime.now(UTC),
            result=c.ToolResult(outcome="DENIED", reason_code="COMPLETION_GATES_UNMET",
                data=c.EntityResult(record_id=verification.id, state_revision=job.state_revision),
                unmet=verification.unmet, event_ids=(event.id,)))
        tx.save_request(receipt)
        return verification, event


def _pending_partial_exception(path):
    job_id, submission_id = proof_ready_job(path)

    def partial(*_):
        result = valid_findings()
        result["findings"]["area_clear"] = False
        return result

    with client_for(path, completion_inspector=partial) as client:
        assert client.post(f"/api/jobs/{job_id}/inspect", headers=headers("setup-partial", 3),
            json={"submission_id": submission_id}).status_code == 200
    verification, denial = _synthetic_settlement_denial(path, job_id)
    with client_for(path) as client:
        raised = client.post(f"/api/jobs/{job_id}/exceptions", headers=headers("setup-exception", 4), json={
            "submission_id": submission_id, "verification_id": verification.id,
            "denial_event_id": denial.id, "reason_code": "completion_incomplete"})
        assert raised.status_code == 202, raised.text
        return job_id, submission_id, raised.json()["data"]["record_id"]


def _operator_context(key, exception_revision=0):
    return c.MutationContext(actor=c.ActorContext(actor_id="demo-operator", actor_type="operator",
        label="District operator (seeded)", district_id="south_loop_demo"),
        operation=Action.REQUEST_COMPLETION.value, idempotency_key=key, expected_revision=exception_revision)


def _service_rework_context(key, job_revision=4):
    return c.MutationContext(actor=c.ActorContext(actor_id="steward-service", actor_type="service",
        label="Steward", district_id="south_loop_demo"), operation=Action.REWORK.value,
        idempotency_key=key, expected_revision=job_revision)


def test_completion_escalation_rejects_mismatched_or_noncompletion_denial(tmp_path):
    job_id, submission_id = proof_ready_job(tmp_path)

    def partial(*_):
        result = valid_findings()
        result["findings"]["area_clear"] = False
        return result

    with client_for(tmp_path, completion_inspector=partial) as client:
        assert client.post(f"/api/jobs/{job_id}/inspect", headers=headers("inspect-mismatch", 3),
            json={"submission_id": submission_id}).status_code == 200
    mismatched = c.VerificationComponents(gps_within_30m=0, after_later_than_before=0,
        target_removed=0, no_new_hazard=0, area_clear=0)
    verification, denied = _synthetic_settlement_denial(tmp_path, job_id, score_components=mismatched)
    with client_for(tmp_path) as client:
        rejected = client.post(f"/api/jobs/{job_id}/exceptions", headers=headers("bad-components", 4), json={
            "submission_id": submission_id, "verification_id": verification.id,
            "denial_event_id": denied.id, "reason_code": "bad-denial"})
        assert rejected.status_code == 422
    # A receipt named like settlement but tied to a non-completion event cannot substitute.
    _verification, unrelated = _synthetic_settlement_denial(tmp_path, job_id, event_type="DISPATCH_DENIED")
    with client_for(tmp_path) as client:
        rejected = client.post(f"/api/jobs/{job_id}/exceptions", headers=headers("bad-kind", 4), json={
            "submission_id": submission_id, "verification_id": verification.id,
            "denial_event_id": unrelated.id, "reason_code": "bad-denial"})
        assert rejected.status_code == 422
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.open_completion_exception(job_id) is None


def test_actual_b5_budget_denial_creates_only_current_budget_exception(tmp_path):
    # Spend six real B5 reservations first; a malformed small budget is not an
    # authentic shortage and must never become a B8 budget exception.
    for index in range(6):
        prior_plan, prior_revision = create_plan(tmp_path, f"prior-{index}")
        with client_for(tmp_path) as client:
            assert dispatch(client, prior_plan, prior_revision, key=f"prior-dispatch-{index}").status_code == 201
    plan_id, issue_revision = create_plan(tmp_path)
    with client_for(tmp_path) as client:
        denial = dispatch(client, plan_id, issue_revision, key="budget-denial")
        assert denial.status_code == 403, denial.text
        assert denial.json()["unmet"] == ["insufficient_budget"]
        raised = client.post("/api/issues/issue/exceptions", headers=headers("budget-exception", issue_revision),
            json={"kind": "budget", "reason_code": "dispatch_budget_shortage",
                  "denial_event_id": denial.json()["event_ids"][0]})
        assert raised.status_code == 202, raised.text
        replay = client.post("/api/issues/issue/exceptions", headers=headers("budget-exception", issue_revision),
            json={"kind": "budget", "reason_code": "dispatch_budget_shortage",
                  "denial_event_id": denial.json()["event_ids"][0]})
        assert replay.json() == raised.json()
    with Store(tmp_path / "b4.sqlite3") as store:
        exception = store.get_exception(raised.json()["data"]["record_id"])
        assert exception.kind == "budget" and exception.job_id is None
        assert store.active_job_for_issue("issue") is None


def test_budget_exception_rejects_non_shortage_dispatch_denial(tmp_path):
    plan_id, issue_revision = create_plan(tmp_path)
    with client_for(tmp_path) as client:
        denial = dispatch(client, plan_id, issue_revision, key="not-budget", vendor="lakefront_clean_team")
        assert denial.status_code == 403 and "vendor_missing_equipment" in denial.json()["unmet"]
        rejected = client.post("/api/issues/issue/exceptions", headers=headers("wrong-budget", issue_revision),
            json={"kind": "budget", "reason_code": "not-a-shortage",
                  "denial_event_id": denial.json()["event_ids"][0]})
        assert rejected.status_code == 422


def _exhausted_budget_denial(path, prefix):
    for index in range(6):
        prior_plan, prior_revision = create_plan(path, f"{prefix}-prior-{index}")
        with client_for(path) as client:
            assert dispatch(client, prior_plan, prior_revision, key=f"{prefix}-dispatch-{index}").status_code == 201
    plan_id, issue_revision = create_plan(path)
    with client_for(path) as client:
        denial = dispatch(client, plan_id, issue_revision, key=f"{prefix}-denial")
        assert denial.status_code == 403 and denial.json()["unmet"] == ["insufficient_budget"]
    return issue_revision, denial.json()["event_ids"][0]


def test_budget_exception_rejects_recovered_or_corrupt_current_funds(tmp_path):
    issue_revision, denial_id = _exhausted_budget_denial(tmp_path, "recover")
    # B9 will own cancellation; this is a typed storage primitive that simulates a
    # legitimate terminal release so B8 can prove an old shortage is no longer current.
    with Store(tmp_path / "b4.sqlite3") as store, store.transaction() as tx:
        job = store.get_job(store.db.execute("SELECT id FROM jobs WHERE issue_id=?", ("recover-prior-0",)).fetchone()[0])
        reservation = store.reservation_for_job(job.id)
        assert reservation is not None
        actor = c.ActorContext(actor_id="steward-service", actor_type="service", label="Steward",
            district_id="south_loop_demo")
        updated_job = job.model_copy(update={"status": "CANCELLED", "state_revision": job.state_revision + 1})
        tx.replace_job(updated_job, job.state_revision)
        released = reservation.model_copy(update={"status": "RELEASED", "closed_at": datetime.now(UTC),
            "state_revision": reservation.state_revision + 1})
        tx.replace_reservation(released, reservation.state_revision)
        event = tx.append_event(c.NewEvent(issue_id=job.issue_id, job_id=job.id,
            event_type="SYNTHETIC_RELEASE_FOR_B8_TEST", timestamp=datetime.now(UTC), actor=actor,
            state_revision=updated_job.state_revision, policy_version="south-loop-v3",
            payload=c.EventFacts(outcome="OK", record_id=job.id, simulated=True)))
        tx.append_ledger(c.LedgerEntry(id=str(uuid4()), budget_id=reservation.budget_id, job_id=job.id,
            reservation_id=reservation.id, kind="RELEASE", amount_cents=reservation.amount_cents,
            event_id=event.id, created_at=datetime.now(UTC)))
    with client_for(tmp_path) as client:
        recovered = client.post("/api/issues/issue/exceptions", headers=headers("recovered", issue_revision),
            json={"kind": "budget", "reason_code": "old-shortage", "denial_event_id": denial_id})
        assert recovered.status_code == 409

    corrupt_revision, corrupt_denial = _exhausted_budget_denial(tmp_path / "corrupt", "corrupt")
    with Store(tmp_path / "corrupt" / "b4.sqlite3") as store:
        # Simulate a damaged on-disk journal; the B8 writer must fail closed rather
        # than treating a database error as evidence of a funding shortage.
        store.db.execute("DROP TRIGGER ledger_no_update")
        store.db.execute("UPDATE ledger SET amount_cents=1 WHERE id=(SELECT id FROM ledger LIMIT 1)")
        store.db.commit()
    with client_for(tmp_path / "corrupt") as client:
        corrupt = client.post("/api/issues/issue/exceptions", headers=headers("corrupt", corrupt_revision),
            json={"kind": "budget", "reason_code": "corrupt-journal", "denial_event_id": corrupt_denial})
        assert corrupt.status_code == 422


def test_budget_exception_rejects_stale_attempted_plan_even_if_funds_remain_short(tmp_path):
    for index in range(6):
        prior_plan, prior_revision = create_plan(tmp_path, f"stale-prior-{index}")
        with client_for(tmp_path) as client:
            assert dispatch(client, prior_plan, prior_revision, key=f"stale-prior-dispatch-{index}").status_code == 201
    plan_id, issue_revision = create_plan(tmp_path)
    with client_for(tmp_path) as client:
        denial = dispatch(client, plan_id, issue_revision, key="stale-budget-denial")
        assert denial.status_code == 403 and denial.json()["unmet"] == ["insufficient_budget"]
    # A newer typed classification supersedes the denied plan's exact fact basis.
    with Store(tmp_path / "b4.sqlite3") as store:
        issue = store.get_issue_record("issue")
        old = store.current_issue_facts("issue").classification
        assert old is not None
        refreshed = old.model_copy(update={"id": "budget-refreshed-classification",
            "source_issue_revision": issue.state_revision, "fact_version": 1})
        inv.save_classification(store, refreshed,
            context=context("save_classification", "refresh-budget-basis", issue.state_revision))
        current_revision = store.get_issue_record("issue").state_revision
    with client_for(tmp_path) as client:
        rejected = client.post("/api/issues/issue/exceptions", headers=headers("stale-budget", current_revision),
            json={"kind": "budget", "reason_code": "stale-shortage",
                  "denial_event_id": denial.json()["event_ids"][0]})
        assert rejected.status_code == 422
    with Store(tmp_path / "b4.sqlite3") as store:
        assert not [item for item in store.exceptions_for_issue("issue") if item.kind == "budget"]


def test_authority_and_no_vendor_exceptions_require_current_facts_and_have_no_job(tmp_path, monkeypatch):
    _fact, authority_revision = prepare(tmp_path, authority="city")
    with client_for(tmp_path) as client:
        authority = client.post("/api/issues/issue/exceptions", headers=headers("authority", authority_revision),
            json={"kind": "authority", "reason_code": "city_responsibility"})
        assert authority.status_code == 202, authority.text
    # The current plan is real; this test supplies no eligible vendor facts through
    # the Store seam rather than inventing an operator-supplied vendor condition.
    plan_id, no_vendor_revision = create_plan(tmp_path, "no-vendor")
    original = Store.list_vendors

    def none_eligible(self):
        return tuple(record.model_copy(update={"available": False}) for record in original(self))

    monkeypatch.setattr(Store, "list_vendors", none_eligible)
    with client_for(tmp_path) as client:
        no_vendor = client.post("/api/issues/no-vendor/exceptions", headers=headers("no-vendor", no_vendor_revision),
            json={"kind": "no_vendor", "reason_code": "no_eligible_vendor"})
        assert no_vendor.status_code == 202, no_vendor.text
    with Store(tmp_path / "b4.sqlite3") as store:
        authority_record = store.get_exception(authority.json()["data"]["record_id"])
        vendor_record = store.get_exception(no_vendor.json()["data"]["record_id"])
        assert authority_record.kind == "authority" and vendor_record.kind == "no_vendor"
        assert authority_record.job_id is None and vendor_record.job_id is None
        assert store.get_plan(plan_id).issue_id == "no-vendor"


def test_partial_completion_denial_becomes_one_operator_choice_then_separate_rework(tmp_path):
    job_id, submission_id = proof_ready_job(tmp_path)

    def partial(*_):
        result = valid_findings()
        result["findings"]["area_clear"] = False
        return result

    with client_for(tmp_path, completion_inspector=partial) as client:
        inspected = client.post(f"/api/jobs/{job_id}/inspect", headers=headers("partial", 3),
            json={"submission_id": submission_id})
        assert inspected.status_code == 200, inspected.text
    verification, denial = _synthetic_settlement_denial(tmp_path, job_id)

    with client_for(tmp_path) as client:
        exception_response = client.post(f"/api/jobs/{job_id}/exceptions", headers=headers("raise", 4), json={
            "submission_id": submission_id, "verification_id": verification.id,
            "denial_event_id": denial.id, "reason_code": "completion_incomplete"})
        assert exception_response.status_code == 202, exception_response.text
        exception_id = exception_response.json()["data"]["record_id"]
        detail = client.get(f"/api/exceptions/{exception_id}", headers=headers("operator-read"))
        assert detail.status_code == 200
        assert detail.json()["data"]["total"] == 90
        assert detail.json()["data"]["findings"]["area_clear"] is False
        assert detail.json()["data"]["job_revision"] == 4

        select_crew(client)
        # Both PENDING and DECIDED exception states must block a replacement proof.
        blocked = client.post(f"/api/jobs/{job_id}/proof", headers=crew_headers("blocked", 4), files={
            "after": ("after.jpg", picture("blue"), "image/jpeg"), "metadata": (None, "{}")})
        assert blocked.status_code == 409

        select_crew(client, "operator")
        operator_headers = {"Origin": ORIGIN, "X-Steward-Request": "1",
            "Idempotency-Key": "operator-choice", "X-Steward-Expected-Revision": "0"}
        stale_exception = {**operator_headers, "Idempotency-Key": "operator-stale",
                           "X-Steward-Expected-Revision": "1"}
        assert client.post(f"/api/exceptions/{exception_id}/request-completion", headers=stale_exception,
            json={"submission_id": submission_id, "expected_job_revision": 4}).status_code == 409
        choice = client.post(f"/api/exceptions/{exception_id}/request-completion", headers=operator_headers,
            json={"submission_id": submission_id, "expected_job_revision": 4})
        assert choice.status_code == 202, choice.text
        assert choice.json()["reason_code"] == "DECISION_SAVED"
        decision_id = choice.json()["data"]["record_id"]
        assert choice.json()["data"]["state_revision"] is None
        assert client.post(f"/api/exceptions/{exception_id}/request-completion", headers=operator_headers,
            json={"submission_id": submission_id, "expected_job_revision": 4}).json() == choice.json()
        other_key = {**operator_headers, "Idempotency-Key": "operator-compatible"}
        assert client.post(f"/api/exceptions/{exception_id}/request-completion", headers=other_key,
            json={"submission_id": submission_id, "expected_job_revision": 4}).json()["data"]["record_id"] == decision_id
        wrong_job = {**operator_headers, "Idempotency-Key": "operator-wrong-job"}
        assert client.post(f"/api/exceptions/{exception_id}/request-completion", headers=wrong_job,
            json={"submission_id": submission_id, "expected_job_revision": 3}).status_code == 409
        select_crew(client)
        assert client.post(f"/api/exceptions/{exception_id}/request-completion", headers=operator_headers,
            json={"submission_id": submission_id, "expected_job_revision": 4}).status_code == 403

        client.cookies.clear()
        rework = client.post(f"/api/operator-decisions/{decision_id}/rework", headers=headers("rework", 4))
        assert rework.status_code == 200, rework.text
        assert rework.json()["data"]["record_id"] == job_id

    with Store(tmp_path / "b4.sqlite3") as store:
        job = store.get_job(job_id)
        exception = store.get_exception(exception_id)
        decision = store.get_operator_decision(decision_id)
        reservation = store.reservation_for_job(job_id)
        assert job.status == "REWORK_REQUIRED" and job.state_revision == 5
        assert exception.status == "HANDLED" and exception.state_revision == 2
        assert decision.handled_at is not None
        assert reservation is not None and reservation.status == "RESERVED"
        assert store.get_submission(submission_id).before_evidence_id == exception.before_evidence_id


def test_diagnostic_hundred_prerequisite_unknown_reworks_without_inventing_debris(tmp_path):
    job_id, submission_id = proof_ready_job(tmp_path)

    def unknown_scene(*_):
        result = valid_findings()
        result["findings"]["same_scene"] = None
        return result

    with client_for(tmp_path, completion_inspector=unknown_scene) as client:
        inspected = client.post(f"/api/jobs/{job_id}/inspect", headers=headers("unknown-scene", 3),
            json={"submission_id": submission_id})
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["data"]["total"] == 100
        assert inspected.json()["data"]["findings"]["same_scene"] is None
    verification, denial = _synthetic_settlement_denial(tmp_path, job_id)
    with client_for(tmp_path) as client:
        raised = client.post(f"/api/jobs/{job_id}/exceptions", headers=headers("raise-unknown", 4), json={
            "submission_id": submission_id, "verification_id": verification.id,
            "denial_event_id": denial.id, "reason_code": "completion_unknown"})
        assert raised.status_code == 202, raised.text
        exception_id = raised.json()["data"]["record_id"]
        select_crew(client, "operator")
        chosen = client.post(f"/api/exceptions/{exception_id}/request-completion", headers={
            "Origin": ORIGIN, "X-Steward-Request": "1", "Idempotency-Key": "unknown-choice",
            "X-Steward-Expected-Revision": "0"}, json={"submission_id": submission_id,
                                                         "expected_job_revision": 4})
        assert chosen.status_code == 202, chosen.text
        client.cookies.clear()
        assert client.post(f"/api/operator-decisions/{chosen.json()['data']['record_id']}/rework",
            headers=headers("unknown-rework", 4)).status_code == 200
    with Store(tmp_path / "b4.sqlite3") as store:
        instructions = store.get_job(job_id).rework_instructions
        assert "same_scene" in instructions
        assert "debris" not in instructions and "remaining material" not in instructions


def test_concurrent_operator_clicks_and_restart_share_one_decision_and_invocation(tmp_path):
    job_id, submission_id, exception_id = _pending_partial_exception(tmp_path)

    def choose(key):
        with Store(tmp_path / "b4.sqlite3") as store:
            return request_completion(store, exception_id=exception_id, submission_id=submission_id,
                expected_job_revision=4, context=_operator_context(key))

    with ThreadPoolExecutor(max_workers=2) as workers:
        first, second = tuple(workers.map(choose, ("concurrent-one", "concurrent-two")))
    first_data, second_data = first.result.data, second.result.data
    assert isinstance(first_data, c.PendingEntityResult) and isinstance(second_data, c.PendingEntityResult)
    assert first_data.record_id == second_data.record_id
    assert first_data.invocation_id == second_data.invocation_id
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_exception(exception_id).status == "DECIDED"
        assert store.db.execute("SELECT COUNT(*) FROM operator_decisions WHERE exception_id=?", (exception_id,)).fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM invocations WHERE trigger_type='OPERATOR_DECISION'").fetchone()[0] == 1
        assert store.get_job(job_id).state_revision == 4


def test_choice_and_rework_faults_roll_back_without_unblocking_proof(tmp_path, monkeypatch):
    job_id, submission_id, exception_id = _pending_partial_exception(tmp_path)
    original_insert = StoreTransaction.insert_pending_invocation

    def fail_invocation(self, spec, trigger):
        raise RuntimeError("fault after operator event")

    monkeypatch.setattr(StoreTransaction, "insert_pending_invocation", fail_invocation)
    with Store(tmp_path / "b4.sqlite3") as store, pytest.raises(RuntimeError, match="fault after operator event"):
        request_completion(store, exception_id=exception_id, submission_id=submission_id,
            expected_job_revision=4, context=_operator_context("fault-choice"))
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_exception(exception_id).status == "PENDING"
        assert store.operator_decision_for_exception(exception_id) is None
        assert store.open_completion_exception(job_id).id == exception_id

    monkeypatch.setattr(StoreTransaction, "insert_pending_invocation", original_insert)
    with Store(tmp_path / "b4.sqlite3") as store:
        decision = request_completion(store, exception_id=exception_id, submission_id=submission_id,
            expected_job_revision=4, context=_operator_context("save-choice")).result.data
        assert isinstance(decision, c.PendingEntityResult)
    def fail_handled(self, decision_id, handled_at):
        raise RuntimeError("fault after rework state")

    monkeypatch.setattr(StoreTransaction, "mark_operator_decision_handled", fail_handled)
    with Store(tmp_path / "b4.sqlite3") as store, pytest.raises(RuntimeError, match="fault after rework state"):
        request_rework(store, decision_id=decision.record_id, context=_service_rework_context("fault-rework"))
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job_id).state_revision == 4
        assert store.get_exception(exception_id).status == "DECIDED"
        assert store.get_operator_decision(decision.record_id).handled_at is None
