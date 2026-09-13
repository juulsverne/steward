"""Storage integrity examples; these do not exercise future business-policy operations."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from agent import contracts as c
from agent.store import RevisionConflict, Store
from agent.verification import VisionFindings

AT = datetime(2026, 9, 13, 12, tzinfo=UTC)
SERVICE = c.ActorContext(actor_id="service", actor_type="service", label="Steward")
CREW = c.ActorContext(actor_id="crew", actor_type="crew", label="Crew", vendor_id="vendor")
OPERATOR = c.ActorContext(actor_id="operator", actor_type="operator", label="Operator")


def event(kind="RECORDS_SAVED", **kwargs):
    return c.NewEvent(issue_id="couch", job_id="job", event_type=kind, actor=SERVICE,
                      timestamp=AT, policy_version="v3", payload=c.EventFacts(**kwargs))


def seeded_records(store):
    """Representative initial job, failed proof, exact denial, reservation and exception."""
    store.create_issue("couch", "bulky_waste", "Demo")
    with store.transaction() as tx:
        tx.insert_vendor(c.VendorRecord(id="vendor", name="Demo crew", insurance_verified=True,
            service_categories=("bulky_waste",), service_area=("district",), equipment=("truck",),
            available=True, distance_km=1.0, workload=0, performance=1.0,
            provenance="seeded", seed_version="v1"))
        tx.insert_budget(c.BudgetRecord(id="district", initial_cents=50000, policy_version="v3"))
        tx.insert_plan(c.PlanRecord(id="plan", issue_id="couch", district_id="district",
            service_type="bulky_waste", condition="Couch", scope="Remove couch and bags",
            work_area="Sidewalk", required_equipment=("truck",), crew_count=2, large_objects=1,
            quote_cents=7200, policy_version="v3", created_at=AT))
        tx.insert_job(c.JobRecord(id="job", issue_id="couch", plan_id="plan", vendor_id="vendor",
            price_cents=7200, status="PROOF_SUBMITTED", created_at=AT))
        for name, role in (("before", "before"), ("middle", "completion"), ("after", "completion")):
            tx.insert_evidence(c.EvidenceRecord(id=name, image_ref=name, image_sha256="a" * 64,
                content_type="image/jpeg", size_bytes=100, provenance="synthetic", received_at=AT))
            tx.associate_evidence(c.EvidenceAssociation(id=f"assoc-{name}", evidence_id=name,
                role=role, issue_id="couch", job_id="job" if role == "completion" else None,
                created_at=AT))
        tx.insert_submission(submission("middle"))
        tx.insert_verification(verification("middle", clear=False))
        denial = tx.append_event(event("SETTLEMENT_DENIED", outcome="DENIED",
                                        submission_id="proof-middle", reason_code="area_clear"))
        tx.insert_exception(c.ExceptionRecord(id="exception", issue_id="couch", job_id="job",
            submission_id="proof-middle", verification_id="verification-middle",
            denial_event_id=denial.id, kind="completion", reason_code="area_clear",
            unmet=("area_clear",), scope="Remove bags", before_evidence_id="before",
            after_evidence_id="middle", created_at=AT))
        tx.insert_reservation(c.ReservationRecord(id="reservation", budget_id="district",
            issue_id="couch", job_id="job", amount_cents=7200, created_at=AT))
        tx.append_ledger(c.LedgerEntry(id="reserved", budget_id="district", job_id="job",
            reservation_id="reservation", kind="RESERVE", amount_cents=7200,
            event_id=denial.id, created_at=AT))
        tx.append_decision(c.DecisionRecord(id="decision", issue_id="couch", job_id="job",
            trigger_event_id=denial.id, decision_type="REQUEST_OPERATOR", summary="Area not clear",
            score_components=verification("middle", clear=False).components,
            policy_version="v3", next_actor="operator", created_at=AT))
    return denial


def submission(after):
    return c.SubmissionRecord(id=f"proof-{after}", issue_id="couch", job_id="job",
        before_evidence_id="before", after_evidence_id=after, submitted_by=CREW,
        submitted_at=AT, job_revision=0)


def verification(after, clear=True):
    return c.VerificationRecord(id=f"verification-{after}", issue_id="couch", job_id="job",
        submission_id=f"proof-{after}", findings=VisionFindings(target_present_before=True,
        same_scene=True, target_removed=True, no_new_hazard=True, area_clear=clear,
        observations=["Clear" if clear else "Bags remain"]),
        components=c.VerificationComponents(gps_within_30m=30, after_later_than_before=10,
            target_removed=40, no_new_hazard=10, area_clear=10 if clear else 0),
        prerequisites=(c.GateRecord(name="same_scene", allowed=True),), policy_version="v3",
        metadata=c.ModelRunMetadata(role="image", model_id="model", vision_model_id="model",
                                   region="us-west-2", prompt_version="p1"),
        inspected_at=AT, job_revision=0)


def payment():
    return c.PaymentRecord(id="payment", issue_id="couch", job_id="job",
        reservation_id="reservation", submission_id="proof-after",
        verification_id="verification-after", amount_cents=7200,
        idempotency_key="payment-key", created_at=AT)


def test_complete_record_graph_reopens_identically(tmp_path):
    path = tmp_path / "case.db"
    with Store(path) as store:
        seeded_records(store)
        before_image = store.get_evidence("before")
        with store.transaction() as tx:
            tx.associate_evidence(c.EvidenceAssociation(id="before-job", evidence_id="before",
                role="before", issue_id="couch", job_id="job", created_at=AT))
            tx.insert_operator_decision(c.OperatorDecisionRecord(id="operator-decision",
                exception_id="exception", issue_id="couch", job_id="job",
                submission_id="proof-middle", actor=OPERATOR, reason="Finish cleanup",
                expected_exception_revision=0, created_at=AT))
            tx.mark_operator_decision_handled("operator-decision", AT)
            tx.replace_exception(store.get_exception("exception").model_copy(update={
                "status": "HANDLED", "handled_at": AT, "state_revision": 1}), 0)
            tx.insert_submission(submission("after"))
            tx.insert_verification(verification("after"))
            paid = tx.append_event(event("SIMULATED_PAYMENT", outcome="OK", simulated=True,
                                         submission_id="proof-after"))
            tx.insert_payment(payment())
            tx.append_ledger(c.LedgerEntry(id="consumed", budget_id="district", job_id="job",
                reservation_id="reservation", payment_id="payment", kind="CONSUME",
                amount_cents=7200, event_id=paid.id, created_at=AT))
            tx.replace_reservation(store.get_reservation("reservation").model_copy(update={
                "status": "CONSUMED", "closed_at": AT, "state_revision": 1}), 0)
            tx.replace_job(store.get_job("job").model_copy(update={"status": "PAID",
                "latest_submission_id": "proof-after", "paid_at": AT, "state_revision": 1}), 0)
            tx.replace_issue(store.get_issue_record("couch").model_copy(update={
                "status": "RESOLVED", "accepted_submission_id": "proof-after",
                "resolved_at": AT, "state_revision": 1}), 0)
        assert store.get_evidence("before") == before_image
        assert len(store.evidence_associations("before")) == 2
        getters = {"get_vendor": "vendor", "get_plan": "plan", "get_job": "job",
                   "get_evidence": "before", "get_submission": "proof-after",
                   "get_verification": "verification-after", "get_exception": "exception",
                   "get_operator_decision": "operator-decision", "get_budget": "district",
                   "get_reservation": "reservation", "get_payment": "payment",
                   "get_ledger_entry": "consumed", "get_decision": "decision",
                   "get_issue_record": "couch"}
        saved = {name: getattr(store, name)(key) for name, key in getters.items()}
    with Store(path) as store:
        assert {name: getattr(store, name)(key) for name, key in getters.items()} == saved
        assert store.get_verification("verification-after").metadata.usage is None
        assert len(store.evidence_for_entity(job_id="job")) == 3
        assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_invalid_cross_issue_records_and_money_are_atomic(tmp_path):
    with Store(tmp_path / "invalid.db") as store:
        seeded_records(store)
        store.create_issue("other", "litter", "Other")
        before = len(store.events("couch"))
        with (
            pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"),
            store.transaction() as tx,
        ):
            tx.append_event(event("MUST_ROLL_BACK"))
            tx.insert_verification(verification("middle").model_copy(update={
                "id": "wrong-issue", "issue_id": "other"}))
        assert len(store.events("couch")) == before
        assert store.db.execute("SELECT count(*) FROM verifications").fetchone()[0] == 1
        with pytest.raises(ValueError, match="differs"), store.transaction() as tx:
            tx.insert_reservation(store.get_reservation("reservation").model_copy(update={
                "id": "another", "amount_cents": 7100}))
        with pytest.raises(ValueError, match="differs"), store.transaction() as tx:
            tx.insert_payment(payment().model_copy(update={"amount_cents": 1}))


def test_exact_proof_associations_and_denial_required(tmp_path):
    with Store(tmp_path / "proof.db") as store:
        seeded_records(store)
        with pytest.raises(ValueError, match="actor/job/issue"), store.transaction() as tx:
            tx.insert_submission(submission("after").model_copy(update={
                "submitted_by": CREW.model_copy(update={"vendor_id": "wrong"})}))
        with (
            pytest.raises(ValueError, match="proof does not match"),
            store.transaction() as tx,
        ):
            tx.insert_exception(store.get_exception("exception").model_copy(update={
                "id": "wrong", "after_evidence_id": "after"}))
        with store.transaction() as tx:
            successful_event = tx.append_event(event("OK", outcome="OK", submission_id="proof-middle"))
        with (
            pytest.raises(ValueError, match="actual same-proof denial"),
            store.transaction() as tx,
        ):
            tx.insert_exception(store.get_exception("exception").model_copy(update={
                "id": "fake-denial", "denial_event_id": successful_event.id}))


def test_unique_business_effects_and_immutable_bytes(tmp_path):
    with Store(tmp_path / "unique.db") as store:
        seeded_records(store)
        for method, original in (
            ("insert_reservation", store.get_reservation("reservation")),
            ("insert_exception", store.get_exception("exception")),
        ):
            with (
                pytest.raises(sqlite3.IntegrityError, match="UNIQUE"),
                store.transaction() as tx,
            ):
                getattr(tx, method)(original.model_copy(update={"id": "duplicate"}))
        with (
            pytest.raises(sqlite3.IntegrityError, match="UNIQUE"),
            store.transaction() as tx,
        ):
            tx.insert_plan(store.get_plan("plan").model_copy(update={"id": "plan2"}))
            tx.insert_job(store.get_job("job").model_copy(update={"id": "job2", "plan_id": "plan2"}))
        assert store.db.execute("SELECT id FROM plans WHERE id='plan2'").fetchone() is None
        # Three separate image identities intentionally retain identical digests for reuse detection.
        assert store.db.execute("SELECT count(*) FROM evidence WHERE image_sha256=?",
                                ("a" * 64,)).fetchone()[0] == 3
        for table in ("evidence", "evidence_associations", "submissions", "verifications", "ledger"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                store.db.execute(f"DELETE FROM {table}")


def test_job_revision_race_and_immutable_contract(tmp_path):
    path = tmp_path / "revisions.db"
    with Store(path) as store:
        seeded_records(store)
        snapshot = store.get_job("job")
        with (
            pytest.raises(ValueError, match="immutable price_cents"),
            store.transaction() as tx,
        ):
            tx.replace_job(snapshot.model_copy(update={"price_cents": 1, "state_revision": 1}), 0)

    def update(number):
        with Store(path) as store:
            try:
                with store.transaction() as tx:
                    tx.replace_job(snapshot.model_copy(update={
                        "rework_instructions": f"Remove bags {number}", "state_revision": 1}), 0)
                    tx.append_event(event("REWORK_SAVED"))
                return "saved"
            except RevisionConflict:
                return "stale"

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(update, (1, 2))) == ["saved", "stale"]
    with Store(path) as store:
        assert store.get_job("job").state_revision == 1
        assert len([e for e in store.events("couch") if e["event_type"] == "REWORK_SAVED"]) == 1


def test_rejected_bundle_leaves_no_success_event_or_new_records(tmp_path):
    with Store(tmp_path / "rollback.db") as store:
        seeded_records(store)
        before = store.events("couch")
        with pytest.raises(RuntimeError, match="crash"), store.transaction() as tx:
            tx.insert_submission(submission("after"))
            tx.insert_verification(verification("after"))
            tx.insert_payment(payment())
            tx.append_event(event("SIMULATED_PAYMENT", outcome="OK"))
            raise RuntimeError("crash before commit")
        assert store.events("couch") == before
        assert store.db.execute("SELECT count(*) FROM payments").fetchone()[0] == 0
        with pytest.raises(KeyError):
            store.get_submission("proof-after")
