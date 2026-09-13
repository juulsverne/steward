"""B5 consumer tests: real saved intake/facts, bounded injected vision, no runtime agent."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest
from test_investigation import ACTOR, AT, context, signal
from test_investigation_repair import client_for, headers, photo

from agent import contracts as c
from agent import investigation as inv
from agent import operations as op
from agent.actors import AccessBoundary, AccessError
from agent.adapters import GeocodeResult, ServiceResult
from agent.store import Store, StoreTransaction


def prepare(path, issue_id="issue", *, objects=1, hazards=(), authority="district", budget=50000,
            second_witness=True):
    path.mkdir(parents=True, exist_ok=True)
    with Store(path / "b4.sqlite3") as store:
        item = photo(store, path, name=issue_id)
        store.create_issue(issue_id, "unclassified", item.reported_location)
        store.link_signal(issue_id, item.id)
        other = signal(issue_id + "-witness", author=issue_id + "-other", image=False,
                       text="Separate observation of blocked walking space")
        if second_witness:
            store.store_signal(other, actor=ACTOR)
            store.link_signal(issue_id, other.id)
        inspection = inv.inspect_intake_photo(store, signal_id=item.id, image_root=path / "images",
            inspector=lambda _: c.IntakePhotoFindings(visible_objects=("couch", "bags")),
            context=context("inspect_intake_photo", issue_id + "-inspect"))
        geocode, _ = inv.record_geocode(store, issue_id=issue_id, signal_id=item.id,
            result=GeocodeResult("MATCH", c.LocationRecord(lat=41.86, lon=-87.63,
                accuracy_m=10.0, provenance="seeded")), context=context("geocode", issue_id))
        revision = store.get_issue_record(issue_id).state_revision
        fact, _ = inv.save_classification(store, c.ClassificationFact(id=issue_id + "-scope",
            issue_id=issue_id, signal_id=item.id, category="bulky_waste", visible_objects=("couch", "bags"),
            hazards=hazards, primary_target="brown couch", full_cleanup_scope="couch and all visible bags",
            marked_work_area="marked sidewalk beside the brick wall", large_object_count=objects,
            supporting_evidence_ids=(store.get_intake_inspection(inspection.data.record_id).evidence_id,),
            source_issue_revision=revision, provenance="synthetic", proposed_by=ACTOR, created_at=AT),
            context=context("classification", issue_id, revision))
        revision = store.get_issue_record(issue_id).state_revision
        inv.save_jurisdiction(store, c.JurisdictionFact(id=issue_id + "-authority", issue_id=issue_id,
            classification_fact_id=fact.id, responsibility=authority, supporting_fact_ids=(geocode.id,),
            source_issue_revision=revision, provenance="seeded", proposed_by=ACTOR, created_at=AT),
            context=context("jurisdiction", issue_id, revision))
        current = store.get_issue_record(issue_id)
        if second_witness and not hazards and authority == "district":
            decision = inv.decide(store, issue_id=issue_id, proposed_type="MARK_ACTIONABLE",
                summary="enough independent evidence", evidence_ids=(),
                context=context("decide", issue_id, current.state_revision))
            inv.apply_investigation_decision(store, issue_id=issue_id, decision_id=decision.id,
                context=context("apply_investigation_decision", issue_id, current.state_revision))
        with store.transaction() as tx:
            if not store.db.execute("SELECT id FROM budgets").fetchone():
                tx.insert_budget(c.BudgetRecord(id="south_loop_demo", initial_cents=budget,
                                               policy_version="south-loop-v3"))
                for vendor in json.loads(Path("data/vendors.json").read_text()):
                    tx.insert_vendor(c.VendorRecord.model_validate_json(json.dumps(
                        vendor | {"seed_version": "test-b5"})))
        return fact.id, store.get_issue_record(issue_id).state_revision


def create_plan(path, issue="issue", **kwargs):
    fact_id, revision = prepare(path, issue, **kwargs)
    with client_for(path) as client:
        response = client.post(f"/api/issues/{issue}/plan", headers=headers("plan-" + issue, revision),
                               json={"classification_fact_id": fact_id})
    assert response.status_code == 201, response.text
    return response.json()["data"]["record_id"], revision + 1


def dispatch(client, plan, revision, key="dispatch", vendor="south_loop_services"):
    return client.post(f"/api/plans/{plan}/dispatch", headers=headers(key, revision),
                       json={"vendor_id": vendor})


def test_plan_freezes_scope_price_provenance_and_dispatch_once_across_restart(tmp_path):
    plan_id, revision = create_plan(tmp_path)
    with client_for(tmp_path) as client:
        offered = client.get(f"/api/plans/{plan_id}/vendors", headers=headers("read"))
        assert offered.status_code == 200, offered.text
        assert [v["id"] for v in offered.json()["data"]["vendors"]] == [
            "south_loop_services", "windy_city_maintenance"]
        first = dispatch(client, plan_id, revision)
        assert first.status_code == 201, first.text
    with client_for(tmp_path) as client:
        assert dispatch(client, plan_id, revision).json() == first.json()
        job_id = first.json()["data"]["record_id"]
        job = client.get(f"/api/jobs/{job_id}", headers=headers("read")).json()["data"]
        assert job["primary_target"] == "brown couch"
        assert job["scope"] == "couch and all visible bags"
        assert job["dispatch_location"]["accuracy_m"] == 10
        assert job["reservation_id"]
    with Store(tmp_path / "b4.sqlite3") as store:
        plan = store.get_plan(plan_id)
        assert plan.quote_cents == 7200 and plan.required_equipment == ("truck", "crew_2")
        assert plan.crew_count == 2 and plan.proof_requirements == c.ProofRequirements()
        assert plan.basis.issue_revision_before_plan == revision - 1
        assert plan.basis.issue_revision_after_plan == revision
        assert plan.basis.classification.source_issue_revision < revision - 1
        assert plan.basis.inspections and plan.basis.evidence_ids
        assert store.get_issue_record("issue").status == "RESOLUTION_ACTIVE"
        assert store.budget_availability("south_loop_demo").model_dump() == {
            "budget_id": "south_loop_demo", "initial_cents": 50000,
            "reserved_cents": 7200, "spent_cents": 0, "available_cents": 42800}
        assert store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


@pytest.mark.parametrize("options,vendor,gate", [
    ({"hazards": ("electrical",)}, "south_loop_services", "unresolved_hazards"),
    ({"authority": "unknown"}, "south_loop_services", "responsibility_not_district"),
    ({"budget": 7100}, "south_loop_services", "budget_unavailable_or_inconsistent"),
    ({"second_witness": False}, "south_loop_services", "evidence_below_threshold"),
    ({"objects": 4}, "south_loop_services", "quote_over_autonomous_limit"),
    ({}, "lakefront_clean_team", "vendor_missing_equipment"),
])
def test_denial_retains_attempt_and_no_money(tmp_path, options, vendor, gate):
    plan, revision = create_plan(tmp_path, **options)
    with client_for(tmp_path) as client:
        response = dispatch(client, plan, revision, vendor=vendor)
        assert response.status_code == 403, response.text
        assert gate in response.json()["unmet"]
        assert dispatch(client, plan, revision, vendor=vendor).json() == response.json()
    with Store(tmp_path / "b4.sqlite3") as store:
        event = store.get_event(response.json()["event_ids"][0])
        assert event.event_type == "DISPATCH_DENIED"
        assert event.payload.dispatch.plan_id == plan
        assert event.payload.dispatch.vendor_id == vendor
        assert event.payload.dispatch.actual_issue_revision == revision
        assert store.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert store.db.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 0


def test_last_funds_are_serialized_across_issues(tmp_path):
    for index in range(5):
        prior, revision = create_plan(tmp_path, "prior" + str(index))
        with client_for(tmp_path) as client:
            response = dispatch(client, prior, revision, key=prior)
            assert response.status_code == 201, response.text
    first, first_revision = create_plan(tmp_path, "first")
    second, second_revision = create_plan(tmp_path, "second")
    barrier = Barrier(2)
    def attempt(pair):
        with client_for(tmp_path) as client:
            barrier.wait()
            return dispatch(client, *pair, key=pair[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ((first, first_revision), (second, second_revision))))
    assert sorted(r.status_code for r in results) == [201, 403]
    assert "insufficient_budget" in next(r for r in results if r.status_code == 403).json()["unmet"]
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.budget_availability("south_loop_demo").available_cents == 6800


@pytest.mark.parametrize("same_key", [True, False])
def test_same_issue_concurrent_retries_have_one_financial_effect(tmp_path, same_key):
    plan, revision = create_plan(tmp_path)
    barrier = Barrier(2)
    def attempt(index):
        with client_for(tmp_path) as client:
            barrier.wait()
            return dispatch(client, plan, revision, key="same" if same_key else str(index))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(r.status_code for r in results) == ([201, 201] if same_key else [201, 409])
    if same_key:
        assert results[0].json() == results[1].json()
    with Store(tmp_path / "b4.sqlite3") as store:
        for table in ("jobs", "reservations", "ledger"):
            assert store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
        assert store.get_issue_record("issue").state_revision == revision + 1


@pytest.mark.parametrize("method", ["insert_job", "insert_reservation", "replace_issue",
                                    "append_event", "save_request", "append_ledger"])
def test_failure_at_each_write_rolls_back_everything(tmp_path, monkeypatch, method):
    plan, revision = create_plan(tmp_path)
    original = getattr(StoreTransaction, method)
    def fail_after(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("injected write failure")
    with monkeypatch.context() as patch:
        patch.setattr(StoreTransaction, method, fail_after)
        with client_for(tmp_path) as client:
            assert dispatch(client, plan, revision).status_code == 500
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_issue_record("issue").state_revision == revision
        assert store.get_issue_record("issue").status == "ACTIONABLE"
        assert not [event for event in store.events("issue") if event["event_type"] == "SIMULATED_DISPATCH"]
        for table in ("jobs", "reservations", "ledger"):
            assert store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert store.request_for_operation(context("dispatch", "dispatch", revision)) is None
    with client_for(tmp_path) as client:
        assert dispatch(client, plan, revision).status_code == 201


def test_plan_and_dispatch_replay_validate_caller_and_saved_scope_first(tmp_path):
    plan, revision = create_plan(tmp_path)
    with client_for(tmp_path) as client:
        first = dispatch(client, plan, revision, vendor="windy_city_maintenance")
        assert first.status_code == 201
        assert dispatch(client, plan, revision).status_code == 409
        replay = client.post("/api/issues/issue/plan", headers=headers("plan-issue", revision - 1),
                            json={"classification_fact_id": "issue-scope"})
        assert replay.status_code == 201
        assert replay.json()["data"] == {"record_id": plan, "state_revision": 0}
        assert client.post("/api/issues/issue/plan", headers=headers("plan-issue", revision - 1),
                           json={"classification_fact_id": "other"}).status_code == 409
    with Store(tmp_path / "b4.sqlite3") as store:
        for role in ("resident", "crew", "operator"):
            actor = ACTOR.model_copy(update={"actor_type": role, "vendor_id": "windy_city_maintenance"})
            with pytest.raises(AccessError):
                op.dispatch_vendor(store, plan_id=plan, vendor_id="windy_city_maintenance",
                    context=context("dispatch", "dispatch", revision).model_copy(update={"actor": actor}))
        with store.transaction() as tx:
            tx.insert_plan(store.get_plan(plan).model_copy(update={"id": "foreign-plan", "district_id": "foreign"}))
        with pytest.raises(AccessError):
            op.dispatch_vendor(store, plan_id=plan, vendor_id="windy_city_maintenance",
                               context=context("dispatch", "dispatch", revision))


def test_http_rejects_model_authority_and_missing_revision(tmp_path):
    fact, revision = prepare(tmp_path)
    with client_for(tmp_path) as client:
        for injected in ({"quote_cents": 1}, {"large_objects": 0}, {"actor": ACTOR.model_dump()},
                         {"budget_cents": 999999}, {"expected_revision": True}):
            response = client.post("/api/issues/issue/plan", headers=headers("bad", revision),
                                   json={"classification_fact_id": fact} | injected)
            assert response.status_code == 422
        assert client.post("/api/issues/issue/plan", headers=headers("no-revision"),
                           json={"classification_fact_id": fact}).status_code == 422
        response = client.post("/api/issues/issue/plan", headers=headers("valid", revision),
                               json={"classification_fact_id": fact})
        plan = response.json()["data"]["record_id"]
        assert client.post(f"/api/plans/{plan}/dispatch", headers=headers("bad", revision + 1),
            json={"vendor_id": "south_loop_services", "price_cents": 1}).status_code == 422
        assert dispatch(client, plan, revision).status_code == 409


@pytest.mark.parametrize("updates", [
    {"available": False}, {"insurance_verified": False}, {"service_area": ("elsewhere",)},
    {"service_categories": ("litter",)}, {"equipment": ("crew_2",)},
])
def test_dispatch_rereads_vendor_after_eligible_read(tmp_path, updates):
    plan, revision = create_plan(tmp_path)
    with client_for(tmp_path) as client:
        assert client.get(f"/api/plans/{plan}/vendors", headers=headers("read")).status_code == 200
    with Store(tmp_path / "b4.sqlite3") as store:
        vendor = store.get_vendor("south_loop_services").model_copy(update=updates)
        store.db.execute("UPDATE vendors SET record_json=? WHERE id=?", (vendor.model_dump_json(), vendor.id))
        store.db.commit()
    with client_for(tmp_path) as client:
        response = dispatch(client, plan, revision)
        assert response.status_code == 403
        assert any(g.startswith("vendor_") for g in response.json()["unmet"])


def test_b4_replacement_invalidates_authority_and_preserves_original_plan(tmp_path):
    plan, revision = create_plan(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        original = store.get_plan(plan)
        fact = store.current_issue_facts("issue").classification.model_copy(update={
            "id": "replacement", "source_issue_revision": revision, "primary_target": "different couch"})
        inv.save_classification(store, fact, context=context("classification", "replacement", revision))
        assert store.current_issue_facts("issue").jurisdiction is None
    with client_for(tmp_path) as client:
        denied = dispatch(client, plan, revision + 1)
        assert denied.status_code == 403
        assert "current_jurisdiction_missing" in denied.json()["unmet"]
        assert client.get(f"/api/plans/{plan}/vendors", headers=headers("read")).status_code == 403
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_plan(plan) == original


@pytest.mark.parametrize("field,value", [("large_object_count", None), ("primary_target", None),
    ("full_cleanup_scope", None), ("marked_work_area", None), ("unknowns", ("scope unclear",))])
def test_incomplete_scope_never_becomes_a_priceable_plan(tmp_path, field, value):
    _fact, revision = prepare(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        current = store.current_issue_facts("issue")
        fact = current.classification.model_copy(update={"id": "incomplete", field: value,
                                                        "source_issue_revision": revision})
        inv.save_classification(store, fact, context=context("classification", "incomplete", revision))
        authority = current.jurisdiction.model_copy(update={"id": "new-authority",
            "classification_fact_id": fact.id, "source_issue_revision": revision + 1})
        inv.save_jurisdiction(store, authority, context=context("jurisdiction", "new", revision + 1))
    with client_for(tmp_path) as client:
        result = client.post("/api/issues/issue/plan", headers=headers("incomplete", revision + 2),
                            json={"classification_fact_id": fact.id})
        assert result.status_code == 403
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.plans_for_issue("issue") == []


def test_current_score_preserves_applied_dispute_and_is_read_only(tmp_path):
    prepare(tmp_path, second_witness=False)
    with Store(tmp_path / "b4.sqlite3") as store:
        source = store.current_issue_facts("issue").classification.signal_id
        assert store.current_evidence_score("issue").total == 65
        inv.record_service_lookup(store, issue_id="issue", signal_id=source,
            result=ServiceResult("MATCH", "311-open", "OPEN"), context=context("lookup", "open"))
        assert store.current_evidence_score("issue").total == 80
        other = signal("other", author="separate", image=False, text="Distinct newer observation")
        store.store_signal(other, actor=ACTOR)
        store.link_signal("issue", other.id)
        inv.record_service_lookup(store, issue_id="issue", signal_id=other.id,
            result=ServiceResult("MATCH", "311-completed", "COMPLETED", AT - timedelta(days=1)),
            context=context("lookup", "completed"))
        assert store.current_evidence_score("issue").total == 85
        revision = store.get_issue_record("issue").state_revision
        decision = inv.decide(store, issue_id="issue", proposed_type="DISPUTE_OFFICIAL_STATUS",
            summary="two independent later observations", evidence_ids=(), context=context("decide", "dispute", revision))
        inv.apply_investigation_decision(store, issue_id="issue", decision_id=decision.id,
            context=context("apply", "dispute", revision))
        original = store.get_issue_record("issue")
        events = store.events("issue")
        for _ in range(3):
            assert store.current_evidence_score("issue").total == 100
        assert store.get_issue_record("issue") == original and store.events("issue") == events
        third = signal("third", author="third", image=False, text="Third different report")
        store.store_signal(third, actor=ACTOR)
        store.link_signal("issue", third.id)
        inv.record_service_lookup(store, issue_id="issue", signal_id=third.id,
            result=ServiceResult("NO_MATCH"), context=context("lookup", "no-match"))
        assert store.current_evidence_score("issue").total == 85
        # A current unresolved geocode removes precision, despite the prior trusted match.
        inv.record_geocode(store, issue_id="issue", signal_id=third.id,
            result=GeocodeResult("NO_MATCH", None), context=context("geocode", "no-match"))
        assert store.current_evidence_score("issue").total == 70


@pytest.mark.parametrize("from_inspection", [False, True])
def test_historical_hazard_survives_benign_current_facts_at_dispatch(tmp_path, from_inspection):
    prepare(tmp_path, hazards=() if from_inspection else ("electrical",))
    with Store(tmp_path / "b4.sqlite3") as store:
        if from_inspection:
            hazardous = photo(store, tmp_path, name="hazard", body=b"different-hazard-bytes")
            store.link_signal("issue", hazardous.id)
            result = inv.inspect_intake_photo(store, signal_id=hazardous.id, image_root=tmp_path / "images",
                inspector=lambda _: c.IntakePhotoFindings(visible_hazards=("electrical",)),
                context=context("inspect_intake_photo", "hazard"))
            source_id = result.data.record_id
        else:
            source_id = "issue-scope"
        current = store.current_issue_facts("issue")
        revision = store.get_issue_record("issue").state_revision
        fact = current.classification.model_copy(update={"id": "benign", "hazards": (),
                                                        "source_issue_revision": revision})
        inv.save_classification(store, fact, context=context("classification", "benign", revision))
        authority = current.jurisdiction.model_copy(update={"id": "compatible",
            "classification_fact_id": fact.id, "source_issue_revision": revision + 1})
        inv.save_jurisdiction(store, authority, context=context("jurisdiction", "compatible", revision + 1))
    with client_for(tmp_path) as client:
        response = client.post("/api/issues/issue/plan", headers=headers("hazard-plan", revision + 2),
                               json={"classification_fact_id": fact.id})
        assert response.status_code == 201, response.text
        denied = dispatch(client, response.json()["data"]["record_id"], revision + 3)
        assert denied.status_code == 403 and "unresolved_hazards" in denied.json()["unmet"]
    with Store(tmp_path / "b4.sqlite3") as store:
        sources = store.get_event(denied.json()["event_ids"][0]).payload.dispatch.hazard_sources
        assert any((s.intake_inspection_id if from_inspection else s.classification_fact_id) == source_id for s in sources)


def test_cached_inspection_uses_requesting_signal_and_original_claim(tmp_path):
    first, _ = create_plan(tmp_path, "first")
    second, revision = create_plan(tmp_path, "second")
    with Store(tmp_path / "b4.sqlite3") as store:
        original = store.get_plan(first).basis.inspections[0]
        cached = store.get_plan(second).basis.inspections[0]
        assert cached.signal_id != original.signal_id
        assert cached.inspection_id != original.inspection_id
        assert cached.source_inspection_id == original.source_inspection_id
        assert cached.claim_id == original.claim_id
        assert store.get_intake_inspection(cached.inspection_id).metadata is None
        assert not store.get_intake_inspection(cached.inspection_id).cache_eligible
        events, before = store.events("second"), store.get_issue_record("second")
        assert op.list_eligible_vendors(store, plan_id=second, actor=ACTOR).outcome == "OK"
        assert store.events("second") == events and store.get_issue_record("second") == before
    with client_for(tmp_path) as client:
        assert dispatch(client, second, revision).status_code == 201


@pytest.mark.parametrize("fenced", [False, True])
def test_error_or_fenced_inspection_cannot_supply_scope_authority(tmp_path, fenced):
    prepare(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        failed = photo(store, tmp_path, name="failure", body=b"failed-fresh-image")
        store.link_signal("issue", failed.id)
        def unavailable(_):
            raise RuntimeError("bounded unavailable inspector")
        result = inv.inspect_intake_photo(store, signal_id=failed.id, image_root=tmp_path / "images",
            inspector=unavailable, context=context("inspect_intake_photo", "failure"))
        record = store.get_intake_inspection(result.data.record_id)
        assert record.outcome == "ERROR"
        if fenced:
            # Model a late successful output retained after its request already failed.
            with store.transaction() as tx:
                tx.insert_intake_inspection(record.model_copy(update={"id": "fenced-success",
                    "outcome": "SUCCESS", "error_code": None, "cache_eligible": False,
                    "findings": c.IntakePhotoFindings(visible_objects=("couch",))}))
        current = store.current_issue_facts("issue")
        revision = store.get_issue_record("issue").state_revision
        fact = current.classification.model_copy(update={"id": "failed-source", "signal_id": failed.id,
            "supporting_evidence_ids": (record.evidence_id,), "source_issue_revision": revision})
        inv.save_classification(store, fact, context=context("classification", "failed-source", revision))
        authority = current.jurisdiction.model_copy(update={"id": "failed-authority",
            "classification_fact_id": fact.id, "source_issue_revision": revision + 1})
        inv.save_jurisdiction(store, authority, context=context("jurisdiction", "failed-source", revision + 1))
    with client_for(tmp_path) as client:
        response = client.post("/api/issues/issue/plan", headers=headers("failed-source", revision + 2),
                               json={"classification_fact_id": fact.id})
        assert response.status_code == 403
        assert "successful_scope_inspection_missing" in response.json()["unmet"]


@pytest.mark.parametrize("terminal", ["CONSUME", "RELEASE"])
def test_terminal_ledger_accounting_never_double_counts_payment(tmp_path, terminal):
    from test_case_records import verification

    plan, revision = create_plan(tmp_path)
    with client_for(tmp_path) as client:
        job_id = dispatch(client, plan, revision).json()["data"]["record_id"]
    with Store(tmp_path / "b4.sqlite3") as store:
        job = store.get_job(job_id)
        reservation = store.reservation_for_job(job.id)
        with store.transaction() as tx:
            payment_id = None
            if terminal == "CONSUME":
                for name, role in (("proof-before", "before"), ("proof-after", "completion")):
                    tx.insert_evidence(c.EvidenceRecord(id=name, image_ref=name, image_sha256="b" * 64,
                        content_type="image/jpeg", size_bytes=10, provenance="synthetic", received_at=AT))
                    tx.associate_evidence(c.EvidenceAssociation(id=name, evidence_id=name, issue_id="issue",
                        job_id=job.id, role=role, created_at=AT))
                tx.insert_submission(c.SubmissionRecord(id="proof", issue_id="issue", job_id=job.id,
                    before_evidence_id="proof-before", after_evidence_id="proof-after", submitted_at=AT,
                    submitted_by=c.ActorContext(actor_id="crew", actor_type="crew", label="Crew",
                        vendor_id=job.vendor_id), job_revision=0))
                tx.insert_verification(verification("after").model_copy(update={"id": "verification",
                    "issue_id": "issue", "job_id": job.id, "submission_id": "proof"}))
                payment_id = "payment"
                tx.insert_payment(c.PaymentRecord(id=payment_id, issue_id="issue", job_id=job.id,
                    reservation_id=reservation.id, submission_id="proof", verification_id="verification",
                    amount_cents=7200, idempotency_key="payment", created_at=AT))
            event = tx.append_event(c.NewEvent(issue_id="issue", job_id=job.id, event_type="TEST_" + terminal,
                actor=ACTOR, timestamp=AT, policy_version="south-loop-v3", payload=c.EventFacts(outcome="OK")))
            tx.append_ledger(c.LedgerEntry(id="terminal", budget_id=reservation.budget_id,
                job_id=job.id, reservation_id=reservation.id, payment_id=payment_id, kind=terminal,
                amount_cents=7200, event_id=event.id, created_at=AT))
            tx.replace_reservation(reservation.model_copy(update={"state_revision": 1, "closed_at": AT,
                "status": "CONSUMED" if terminal == "CONSUME" else "RELEASED"}), 0)
            tx.replace_job(job.model_copy(update={"state_revision": 1,
                "status": "PAID" if terminal == "CONSUME" else "CANCELLED"}), 0)
    with Store(tmp_path / "b4.sqlite3") as store:
        budget = store.budget_availability("south_loop_demo")
        assert budget.reserved_cents == 0
        assert budget.spent_cents == (7200 if terminal == "CONSUME" else 0)
        assert budget.available_cents == (42800 if terminal == "CONSUME" else 50000)


def test_inconsistent_journal_and_legacy_plan_fail_closed(tmp_path):
    plan, revision = create_plan(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        with store.transaction() as tx:
            tx.insert_plan(store.get_plan(plan).model_copy(update={"id": "legacy", "basis": None}))
        result = op.dispatch_vendor(store, plan_id="legacy", vendor_id="south_loop_services",
                                    context=context("dispatch", "legacy", revision))
        assert "legacy_plan_without_basis" in result.result.unmet
    with client_for(tmp_path) as client:
        job = dispatch(client, plan, revision).json()["data"]["record_id"]
    with Store(tmp_path / "b4.sqlite3") as store:
        reservation = store.reservation_for_job(job)
        with store.transaction() as tx:
            tx.replace_reservation(reservation.model_copy(update={"status": "RELEASED",
                "state_revision": 1, "closed_at": AT}), 0)
        with pytest.raises(ValueError, match="lifecycle"):
            store.budget_availability("south_loop_demo")


def test_crew_projection_is_own_job_only_and_no_financial_authority(tmp_path):
    plan, revision = create_plan(tmp_path)
    with client_for(tmp_path) as client:
        job_id = dispatch(client, plan, revision).json()["data"]["record_id"]
    with Store(tmp_path / "b4.sqlite3") as store:
        actor = ACTOR.model_copy(update={"actor_id": "crew", "actor_type": "crew",
                                        "vendor_id": "south_loop_services"})
        boundary = AccessBoundary(actor, "south_loop_demo")
        view = boundary.job(store, job_id)
        assert view.status == "POSTED" and view.required_equipment == ("truck", "crew_2")
        assert "basis" not in view.model_dump() and "evidence_ids" not in view.model_dump()
        with pytest.raises(AccessError):
            AccessBoundary(actor.model_copy(update={"vendor_id": "other"}), "south_loop_demo").job(store, job_id)


@pytest.mark.parametrize("location,gate", [
    (c.LocationRecord(lat=41.86, lon=-87.63, accuracy_m=None, provenance="seeded"), "location_not_precise"),
    (c.LocationRecord(lat=41.86, lon=-87.63, accuracy_m=31.0, provenance="seeded"), "location_not_precise"),
    (c.LocationRecord(lat=42.0, lon=-87.63, accuracy_m=10.0, provenance="seeded"), "outside_district"),
])
def test_dispatch_uses_current_location_without_rewriting_frozen_coordinates(tmp_path, location, gate):
    plan, _revision = create_plan(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        original = store.get_plan(plan)
        inv.record_geocode(store, issue_id="issue", signal_id="issue-witness",
            result=GeocodeResult("MATCH", location), context=context("geocode", "changed"))
        revision = store.get_issue_record("issue").state_revision
        assert store.current_issue_facts("issue").geocode.location == location
        if location.accuracy_m is None:
            assert store.get_issue_record("issue").components.precise_geocode == 0
    with client_for(tmp_path) as client:
        response = dispatch(client, plan, revision)
        assert response.status_code == 403 and gate in response.json()["unmet"]
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_plan(plan) == original


def test_http_human_roles_cannot_plan_dispatch_or_read_budget_as_crew(tmp_path):
    plan, revision = create_plan(tmp_path)
    with client_for(tmp_path) as client:
        spec = client.get("/openapi.json").json()
        for route in ("/api/issues/{issue_id}/plan", "/api/plans/{plan_id}/dispatch"):
            parameters = spec["paths"][route]["post"]["parameters"]
            assert {p["name"] for p in parameters if p.get("required") and p["in"] == "header"} == {
                "Idempotency-Key", "X-Steward-Expected-Revision"}
        human_headers = {"Origin": "http://localhost:8000", "X-Steward-Request": "1",
                         "Idempotency-Key": "human", "X-Steward-Expected-Revision": str(revision)}
        for persona in ("resident-1", "crew-south_loop_services", "operator"):
            selection = client.post("/api/demo/persona", headers=human_headers, json={"persona_id": persona})
            assert selection.status_code == 200, selection.text
            assert client.post("/api/issues/issue/plan", headers=human_headers,
                               json={"classification_fact_id": "issue-scope"}).status_code == 403
            assert client.post(f"/api/plans/{plan}/dispatch", headers=human_headers,
                               json={"vendor_id": "south_loop_services"}).status_code == 403
            budget = client.get("/api/budget")
            assert budget.status_code == (200 if persona == "operator" else 403)
            if persona == "operator":
                assert budget.json()["data"]["available_cents"] == 50000
