from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agent import contracts as c
from agent.adapters import GeocodeResult, ServiceResult
from agent.config import ApiSettings
from agent.images import NormalizedImage
from agent.intake import persist_signal, resident_signal
from agent.investigation import (
    apply_investigation_decision,
    create_issue_from_signal,
    decide,
    inspect_intake_photo,
    link_signal_to_issue,
    record_geocode,
    record_service_lookup,
    save_classification,
    save_jurisdiction,
)
from agent.models import Signal
from agent.store import IdempotencyConflict, Store

AT = datetime(2026, 9, 12, 14, tzinfo=UTC)
ACTOR = c.ActorContext(actor_id="steward-service", actor_type="service", label="Steward",
                       district_id="south_loop_demo")
IMAGE = NormalizedImage(b"jpeg", "a" * 64, "1" * 16)
ORIGIN = "http://localhost:8000"
TOKEN = "b198d27f3ce40596a180f24d83b710e59603c147ed0f96ca5248ab031d7629fe"
SIGNING = "7a9c4e63b081f205d92461a37c90586ef413ab290675d8ebca013b25e74609df"


def context(operation="investigate", key="key", revision=None):
    return c.MutationContext(actor=ACTOR, operation=operation, idempotency_key=key,
                             expected_revision=revision)


def propose(store, decision_type, key):
    return decide(store, issue_id="issue", proposed_type=decision_type,
                  summary="saved model proposal", evidence_ids=(), context=context(key=key,
                    revision=store.get_issue_record("issue").state_revision))


def signal(signal_id="first", *, author="resident-1", text="Couch and bags block the sidewalk",
           image=True, observed=AT, dhash="1" * 16):
    return Signal(id=signal_id, source="fixture", source_author_id=author,
        source_role="resident_observation", raw_text=text, reported_location="1530 S Michigan Ave",
        received_at=observed + timedelta(minutes=5), observed_at=observed, provenance="seeded",
        image_sha256=("a" * 64 if image else None), image_dhash=(dhash if image else None))


def linked_store(tmp_path, *, first=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = Store(tmp_path / "b4.sqlite3")
    first = first or signal()
    store.store_signal(first, actor=ACTOR)
    store.create_issue("issue", "unclassified", first.reported_location)
    store.link_signal("issue", first.id)
    return store, first


def facts(store, item, *, category="bulky_waste", hazards=(), target="couch"):
    issue = store.get_issue_record("issue")
    classified = c.ClassificationFact(id="classification", issue_id="issue", signal_id=item.id,
        category=category, hazards=hazards, primary_target=target, full_cleanup_scope="couch and bags",
        marked_work_area="sidewalk", large_object_count=1, source_issue_revision=issue.state_revision,
        provenance="seeded", proposed_by=ACTOR, created_at=AT)
    save_classification(store, classified, context=context(key="classification", revision=issue.state_revision))
    issue = store.get_issue_record("issue")
    jurisdiction = c.JurisdictionFact(id="jurisdiction", issue_id="issue",
        classification_fact_id=classified.id, responsibility="district", source_issue_revision=issue.state_revision,
        provenance="seeded", proposed_by=ACTOR, created_at=AT)
    save_jurisdiction(store, jurisdiction, context=context(key="jurisdiction", revision=issue.state_revision))
    return classified, jurisdiction


def test_unlinked_signal_creates_one_candidate_issue_and_exact_replay(tmp_path):
    with Store(tmp_path / "case.sqlite3") as store:
        item = signal()
        store.store_signal(item, actor=ACTOR)
        request = context("create_issue_from_signal", "create")
        first = create_issue_from_signal(store, signal_id=item.id, rationale="no confident candidate", context=request)
        assert first.result.data.record_id
        created = store.get_issue_record(first.result.data.record_id)
        assert created.category == "unclassified" and created.status == "CANDIDATE"
        assert created.signal_ids == (item.id,)
        assert create_issue_from_signal(store, signal_id=item.id, rationale="no confident candidate", context=request) == first
        with pytest.raises(IdempotencyConflict):
            create_issue_from_signal(store, signal_id=item.id, rationale="changed rationale",
                                     context=context("create_issue_from_signal", "other"))


def test_explicit_candidate_link_is_idempotent_and_never_joins_a_second_issue(tmp_path):
    store, _item = linked_store(tmp_path)
    try:
        candidate = signal("candidate", author="resident-2", text="Different wording, same couch", image=False)
        store.store_signal(candidate, actor=ACTOR)
        request = context("link_signal", "link", store.get_issue_record("issue").state_revision)
        first = link_signal_to_issue(store, issue_id="issue", signal_id=candidate.id,
            rationale="same marked sidewalk", context=request)
        assert link_signal_to_issue(store, issue_id="issue", signal_id=candidate.id,
            rationale="same marked sidewalk", context=request) == first
        store.create_issue("other", "unclassified", candidate.reported_location)
        with pytest.raises(IdempotencyConflict):
            link_signal_to_issue(store, issue_id="other", signal_id=candidate.id,
                rationale="nearby but distinct", context=context("link_signal", "other",
                    store.get_issue_record("other").state_revision))
    finally:
        store.db.close()


def test_seeded_adapters_record_history_current_facts_and_no_match(tmp_path):
    store, item = linked_store(tmp_path)
    try:
        geo, _ = record_geocode(store, issue_id="issue", signal_id=item.id,
            result=GeocodeResult("MATCH", c.LocationRecord(lat=41.86102, lon=-87.62406,
                accuracy_m=10, provenance="seeded")), context=context(key="geo"))
        lookup, _ = record_service_lookup(store, issue_id="issue", signal_id=item.id,
            result=ServiceResult("MATCH", "311", "COMPLETED", datetime(2026, 9, 11, tzinfo=UTC)),
            context=context(key="lookup"))
        assert store.latest_service_lookup("issue") == lookup
        current = store.current_issue_facts("issue")
        assert current.geocode == geo and current.geocode.location.accuracy_m == 10
        assert store.get_issue_record("issue").evidence_score == 65
        other = signal("unmatched", author="resident-2", text="A couch on an unknown block", image=False)
        store.store_signal(other, actor=ACTOR)
        store.link_signal("issue", other.id)
        no_match, _ = record_service_lookup(store, issue_id="issue", signal_id=other.id,
            result=ServiceResult("NO_MATCH"), context=context(key="lookup-2"))
        assert no_match.outcome == "NO_MATCH"
        assert len(store.service_lookups_for_issue("issue")) == 2
    finally:
        store.db.close()


def test_decisions_cover_wait_actionable_official_dispute_routes_and_review(tmp_path):
    store, item = linked_store(tmp_path)
    try:
        record_geocode(store, issue_id="issue", signal_id=item.id,
            result=GeocodeResult("MATCH", c.LocationRecord(lat=41.86102, lon=-87.62406,
                accuracy_m=10, provenance="seeded")), context=context(key="geo"))
        record_service_lookup(store, issue_id="issue", signal_id=item.id,
            result=ServiceResult("MATCH", "311", "COMPLETED", datetime(2026, 9, 11, tzinfo=UTC)),
            context=context(key="lookup"))
        facts(store, item)
        current = store.current_issue_facts("issue")
        assert current.issue_revision == store.get_issue_record("issue").state_revision
        assert current.classification is not None
        assert current.classification.source_issue_revision < current.issue_revision
        assert current.jurisdiction is not None
        assert current.jurisdiction.source_issue_revision == current.classification.source_issue_revision + 1
        wait = propose(store, "MONITOR", "wait")
        assert wait.decision_type == "MONITOR" and "independent" in wait.summary
        with pytest.raises(ValueError, match="MARK_ACTIONABLE gate failed"):
            propose(store, "MARK_ACTIONABLE", "invalid-action")
        second = signal("second", author="resident-2", text="Sofa and bags remain at the corner", image=False,
            observed=AT + timedelta(hours=1))
        store.store_signal(second, actor=ACTOR)
        store.link_signal("issue", second.id)
        dispute = propose(store, "DISPUTE_OFFICIAL_STATUS", "dispute")
        assert dispute.decision_type == "DISPUTE_OFFICIAL_STATUS"
        assert store.get_issue_record("issue").evidence_score == 85
        applied = apply_investigation_decision(store, issue_id="issue", decision_id=dispute.id,
            context=context("apply_investigation_decision", "apply-dispute",
                            store.get_issue_record("issue").state_revision))
        assert applied.result.event_ids
        assert store.get_issue_record("issue").evidence_score == 100
    finally:
        store.db.close()


def test_second_independent_text_reaches_85_and_open_record_reaches_80(tmp_path):
    store, item = linked_store(tmp_path / "second")
    try:
        record_geocode(store, issue_id="issue", signal_id=item.id,
            result=GeocodeResult("MATCH", c.LocationRecord(lat=41.86102, lon=-87.62406,
                accuracy_m=10, provenance="seeded")), context=context(key="geo"))
        facts(store, item)
        second = signal("second", author="resident-2", text="A different witness sees the couch and bags", image=False)
        store.store_signal(second, actor=ACTOR)
        store.link_signal("issue", second.id)
        assert store.get_issue_record("issue").evidence_score == 85
        assert propose(store, "MARK_ACTIONABLE", "85").decision_type == "MARK_ACTIONABLE"
        assert store.get_issue_record("issue").status == "CANDIDATE"
    finally:
        store.db.close()
    store, item = linked_store(tmp_path / "open")
    try:
        record_geocode(store, issue_id="issue", signal_id=item.id,
            result=GeocodeResult("MATCH", c.LocationRecord(lat=41.86102, lon=-87.62406,
                accuracy_m=10, provenance="seeded")), context=context(key="geo"))
        record_service_lookup(store, issue_id="issue", signal_id=item.id,
            result=ServiceResult("MATCH", "311-open", "OPEN"), context=context(key="open"))
        facts(store, item)
        assert store.get_issue_record("issue").evidence_score == 80
        assert propose(store, "MARK_ACTIONABLE", "80").decision_type == "MARK_ACTIONABLE"
    finally:
        store.db.close()


def test_unknown_location_official_lookup_and_stale_or_foreign_fact_are_rejected(tmp_path):
    store, item = linked_store(tmp_path)
    try:
        no_match, _ = record_geocode(store, issue_id="issue", signal_id=item.id,
            result=GeocodeResult("NO_MATCH", None), context=context(key="unknown"))
        assert no_match.location is None and store.get_issue_record("issue").components.precise_geocode == 0
        official = Signal(id="official", source="311", source_author_id="311", source_role="official_record",
            raw_text="completed", reported_location=item.reported_location, received_at=AT, provenance="seeded")
        store.store_signal(official, actor=ACTOR)
        store.link_signal("issue", official.id)
        with pytest.raises(ValueError, match="official"):
            record_service_lookup(store, issue_id="issue", signal_id=official.id,
                result=ServiceResult("NO_MATCH"), context=context(key="official"))
        issue = store.get_issue_record("issue")
        invalid = c.ClassificationFact(id="bad", issue_id="issue", signal_id=item.id,
            category="bulky_waste", supporting_evidence_ids=("missing",), source_issue_revision=issue.state_revision,
            provenance="live", proposed_by=ACTOR, created_at=AT)
        with pytest.raises(ValueError, match="evidence"):
            save_classification(store, invalid, context=context(key="bad", revision=issue.state_revision))
    finally:
        store.db.close()


def test_same_author_fresh_distinct_image_awards_persistence_once(tmp_path):
    first = signal(dhash="0000000000000000")
    later = signal("later", author="resident-1", text="Still blocked today", image=True,
        observed=AT + timedelta(hours=24), dhash="ffffffffffffffff")
    later = Signal(**{**later.to_dict(), "image_sha256": "c" * 64})
    with Store(tmp_path / "persistence.sqlite3") as store:
        store.create_issue("issue", "bulky_waste", first.reported_location)
        store.add_signal("issue", first)
        store.add_signal("issue", later)
        store.record_geocode("issue", accuracy_m=10, provenance="seeded")
        assert store.get_issue_record("issue").components.persistence == 10
        assert store.get_issue_record("issue").evidence_score == 75


@pytest.mark.parametrize(("category", "hazards", "responsibility", "expected"), [
    ("pothole", (), "city", "ROUTE_EXTERNAL"),
    ("bulky_waste", ("electrical",), "district", "REQUEST_OPERATOR"),
    ("bulky_waste", (), "private", "REQUEST_OPERATOR"),
])
def test_route_and_safety_gates_use_current_classification_and_jurisdiction(
        tmp_path, category, hazards, responsibility, expected):
    store, item = linked_store(tmp_path)
    try:
        record_geocode(store, issue_id="issue", signal_id=item.id,
            result=GeocodeResult("MATCH", c.LocationRecord(lat=41.86102, lon=-87.62406,
                accuracy_m=10, provenance="seeded")), context=context(key="geo"))
        _classified, jurisdiction = facts(store, item, category=category, hazards=hazards)
        issue = store.get_issue_record("issue")
        jurisdiction = jurisdiction.model_copy(update={"responsibility": responsibility,
            "source_issue_revision": issue.state_revision, "fact_version": 2, "id": "jurisdiction-2"})
        save_jurisdiction(store, jurisdiction, context=context(key="jurisdiction-2", revision=issue.state_revision))
        assert propose(store, expected, "route").decision_type == expected
    finally:
        store.db.close()


def test_copied_canonical_image_is_not_a_second_witness_but_new_text_is(tmp_path):
    from pathlib import Path

    from agent.images import decode_upload, dhash, hamming

    source = Path("data/images/before.jpg")
    raw = source.read_bytes()
    normalized = decode_upload(raw, "image/jpeg")
    original_sha = hashlib.sha256(raw).hexdigest()
    assert original_sha != normalized.image_sha256
    assert hamming(dhash(source), normalized.image_dhash) <= 6
    first = replace(signal(image=True), image_sha256=original_sha, image_dhash=dhash(source))
    second = signal("copy", author="resident-2", text="Different words about the same object", image=True,
                    dhash=normalized.image_dhash)
    second = replace(second, image_sha256=normalized.image_sha256)
    with Store(tmp_path / "copy.sqlite3") as store:
        store.create_issue("issue", "bulky_waste", first.reported_location)
        store.add_signal("issue", first)
        store.add_signal("issue", second)
        assert store.get_issue_record("issue").components.independent_sources == 20
        text_only = signal("text", author="resident-3", text="A couch and bags block the sidewalk here", image=False)
        store.add_signal("issue", text_only)
        assert store.get_issue_record("issue").components.independent_sources == 40


def test_intake_inspection_uses_stored_bytes_caches_success_and_keeps_error_receipt(tmp_path, monkeypatch):
    from agent import investigation

    image_bytes = b"stored-jpeg"
    image = NormalizedImage(image_bytes, hashlib.sha256(image_bytes).hexdigest(), "2" * 16)
    with Store(tmp_path / "inspection.sqlite3") as store:
        item = resident_signal(actor=ACTOR.model_copy(update={"actor_type": "resident", "actor_id": "resident"}),
            idempotency_key="photo", description="couch", location="1530 S Michigan Ave", received_at=AT,
            observed_at=AT - timedelta(minutes=1), image=image, provenance="synthetic")
        persist_signal(store, signal=item, context=c.MutationContext(
            actor=ACTOR, operation="ingest_source", idempotency_key="photo"), image=image,
            image_root=tmp_path / "images", provenance="synthetic")
        calls = []
        def fake(bytes_):
            calls.append(bytes_)
            return c.IntakePhotoFindings(visible_objects=("couch",), observations=("couch visible",))
        inspect_context = context("inspect", "photo-inspect")
        first = inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
            inspector=fake, context=inspect_context)
        second = inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
            inspector=fake, context=inspect_context)
        assert first == second and calls == [image.bytes]
        saved = store.get_intake_inspection(first.data.record_id)
        assert saved.outcome == "SUCCESS" and saved.findings.visible_objects == ("couch",)
        monkeypatch.setattr(investigation, "settings", replace(investigation.settings,
            vision_model_id="configured-image-model-v2"))
        changed = inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
            inspector=fake, context=context("inspect", "changed-model"))
        assert changed.data.record_id != first.data.record_id and calls == [image.bytes, image.bytes]
        failing_bytes = b"failing-stored-jpeg"
        failing_image = NormalizedImage(failing_bytes, hashlib.sha256(failing_bytes).hexdigest(), "3" * 16)
        failed_signal = resident_signal(actor=ACTOR.model_copy(update={"actor_type": "resident", "actor_id": "other"}),
            idempotency_key="failure", description="couch", location="1530 S Michigan Ave", received_at=AT,
            observed_at=AT - timedelta(minutes=1), image=failing_image, provenance="synthetic")
        persist_signal(store, signal=failed_signal, context=c.MutationContext(
            actor=ACTOR, operation="ingest_source", idempotency_key="failure"), image=failing_image,
            image_root=tmp_path / "images", provenance="synthetic")
        def failed(_):
            raise RuntimeError("offline failure")
        failure_context = context("inspect", "failed-inspection")
        error = inspect_intake_photo(store, signal_id=failed_signal.id, image_root=tmp_path / "images",
            inspector=failed, context=failure_context)
        retry = inspect_intake_photo(store, signal_id=failed_signal.id, image_root=tmp_path / "images",
            inspector=failed, context=failure_context)
        assert error == retry and error.outcome == "ERROR" and error.reason_code == "INSPECTION_FAILED"


def test_signal_evidence_scope_covers_only_the_inspected_unlinked_intake_image(tmp_path):
    """Intake inspection reads the signal's own image before any issue link exists."""
    from agent.actors import AccessBoundary, AccessError
    from agent.policy import load_policy

    with Store(tmp_path / "scope.sqlite3") as store:
        images = {}
        for key, digit in (("own", "4"), ("other", "5")):
            raw = f"{key}-jpeg".encode()
            image = NormalizedImage(raw, hashlib.sha256(raw).hexdigest(), digit * 16)
            signal = resident_signal(actor=ACTOR.model_copy(update={"actor_type": "resident", "actor_id": key}),
                idempotency_key=key, description="couch", location="1530 S Michigan Ave", received_at=AT,
                observed_at=AT - timedelta(minutes=1), image=image, provenance="synthetic")
            persist_signal(store, signal=signal, context=c.MutationContext(
                actor=ACTOR, operation="ingest_source", idempotency_key=key), image=image,
                image_root=tmp_path / "images", provenance="synthetic")
            images[key] = (signal.id, store.evidence_for_entity(signal_id=signal.id)[0].id)
        boundary = AccessBoundary(ACTOR, load_policy()["district"])
        own_signal, own_image = images["own"]
        _, other_image = images["other"]
        assert boundary.signal_evidence(store, own_signal, own_image).id == own_image
        with pytest.raises(AccessError):
            boundary.signal_evidence(store, own_signal, other_image)
        # The general read path still refuses an unlinked signal-only association.
        with pytest.raises(AccessError):
            boundary.evidence(store, own_image)


def test_service_only_create_and_intake_inspection_http_paths(tmp_path):
    from agent.api import create_app

    db, images = tmp_path / "api.sqlite3", tmp_path / "images"
    with Store(db) as store:
        item = signal("unlinked")
        store.store_signal(item, actor=ACTOR)
    calls = []
    app = create_app(ApiSettings(store_path=db, image_root=images, origin=ORIGIN, local_http=True,
        session_secret=SIGNING, service_token=TOKEN), intake_inspector=lambda _: calls.append(1))
    headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "create"}
    with TestClient(app, base_url=ORIGIN) as client:
        denied = client.post("/api/issues", json={"signal_id": "unlinked", "match_rationale": "new"},
            headers={"Origin": ORIGIN, "X-Steward-Request": "1", "Idempotency-Key": "human"})
        assert denied.status_code == 401
        created = client.post("/api/issues", json={"signal_id": "unlinked", "match_rationale": "new"},
            headers=headers)
        assert created.status_code == 201
        assert created.json()["data"]["record_id"]
        assert client.post("/api/signals/unlinked/intake-inspection", headers={
            "Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "inspect"}).json()["outcome"] == "NOT_FOUND"
    assert calls == []


def test_decision_http_requires_a_proposal_and_returns_its_persisted_event(tmp_path):
    from agent.api import create_app

    db, images = tmp_path / "decision.sqlite3", tmp_path / "images"
    store, item = linked_store(tmp_path / "prepared")
    try:
        record_geocode(store, issue_id="issue", signal_id=item.id,
            result=GeocodeResult("MATCH", c.LocationRecord(lat=41.86102, lon=-87.62406,
                accuracy_m=10, provenance="seeded")), context=context(key="geo"))
        facts(store, item)
    finally:
        store.db.close()
    (tmp_path / "prepared" / "b4.sqlite3").replace(db)
    app = create_app(ApiSettings(store_path=db, image_root=images, origin=ORIGIN, local_http=True,
        session_secret=SIGNING, service_token=TOKEN))
    with Store(db) as reopened:
        initial_revision = reopened.get_issue_record("issue").state_revision
    headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "decision",
               "X-Steward-Expected-Revision": str(initial_revision)}
    with TestClient(app, base_url=ORIGIN) as client:
        # A well-formed proposal that current facts do not permit is a recoverable denial for the
        # agent loop (it may choose another intent), never a fatal validation error.
        rejected = client.post("/api/issues/issue/decisions", headers=headers,
            json={"decision_type": "MARK_ACTIONABLE", "summary": "claim action", "evidence_ids": []})
        assert rejected.status_code == 403, rejected.text
        assert rejected.json()["outcome"] == "DENIED"
        assert rejected.json()["reason_code"] == "DECISION_GATE_UNMET"
        assert "evidence_threshold" in rejected.json()["unmet"] and rejected.json()["event_ids"] == []
        premature = client.post("/api/issues/issue/decisions", headers={**headers, "Idempotency-Key": "dispute"},
            json={"decision_type": "DISPUTE_OFFICIAL_STATUS", "summary": "one photo is not enough", "evidence_ids": []})
        assert premature.status_code == 403 and premature.json()["outcome"] == "DENIED"
        assert premature.json()["unmet"] == ["two_independent_newer_observations"]
        malformed = client.post("/api/issues/issue/decisions", headers={**headers, "Idempotency-Key": "malformed"},
            json={"decision_type": "MONITOR", "summary": "bad evidence", "evidence_ids": ["not-an-issue-image"]})
        assert malformed.status_code == 422 and malformed.json()["outcome"] == "ERROR"
        accepted = client.post("/api/issues/issue/decisions", headers={**headers, "Idempotency-Key": "monitor"},
            json={"decision_type": "MONITOR", "summary": "needs more evidence", "evidence_ids": []})
    payload = accepted.json()
    assert accepted.status_code == 200
    assert len(payload["event_ids"]) == 1
    with Store(db) as reopened:
        decision = reopened.get_decision(payload["data"]["record_id"])
        assert decision.trigger_event_id != payload["event_ids"][0]
        assert reopened.get_event(decision.trigger_event_id).event_type == "INVESTIGATION_REQUESTED"
        assert reopened.get_issue_record("issue").status == "CANDIDATE"
        revision = reopened.get_issue_record("issue").state_revision
    action_headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "apply-monitor",
                      "X-Steward-Expected-Revision": str(revision)}
    with TestClient(app, base_url=ORIGIN) as client:
        applied = client.post("/api/issues/issue/investigation-action", headers=action_headers,
            json={"decision_id": payload["data"]["record_id"]})
        replay = client.post("/api/issues/issue/investigation-action", headers=action_headers,
            json={"decision_id": payload["data"]["record_id"]})
        stale = client.post("/api/issues/issue/investigation-action", headers={
            **action_headers, "Idempotency-Key": "stale-monitor"},
            json={"decision_id": payload["data"]["record_id"]})
    assert applied.status_code == 200 and replay.json() == applied.json()
    assert stale.status_code == 409
    with Store(db) as reopened:
        assert reopened.get_issue_record("issue").status == "MONITORING"


def test_fact_receipts_replay_before_stale_revision_and_reject_changed_payload(tmp_path):
    store, item = linked_store(tmp_path)
    try:
        first_context = context(key="geo")
        first, receipt = record_geocode(store, issue_id="issue", signal_id=item.id,
            result=GeocodeResult("MATCH", c.LocationRecord(lat=41.86102, lon=-87.62406,
                accuracy_m=10, provenance="seeded")), context=first_context)
        facts(store, item)
        replay, replay_receipt = record_geocode(store, issue_id="issue", signal_id=item.id,
            result=GeocodeResult("MATCH", c.LocationRecord(lat=41.86102, lon=-87.62406,
                accuracy_m=10, provenance="seeded")), context=first_context)
        assert replay == first and replay_receipt == receipt
        # Adapter output is server-selected, not a caller argument; an old key freezes it.
        assert record_geocode(store, issue_id="issue", signal_id=item.id,
            result=GeocodeResult("NO_MATCH", None), context=first_context) == (first, receipt)
        other = signal("other", image=False)
        store.store_signal(other, actor=ACTOR)
        store.link_signal("issue", other.id)
        with pytest.raises(IdempotencyConflict):
            record_geocode(store, issue_id="issue", signal_id=other.id,
                result=GeocodeResult("NO_MATCH", None), context=first_context)
    finally:
        store.db.close()


def test_api_interpretation_receipts_replay_and_preserve_seeded_evidence_provenance(tmp_path):
    from agent.api import create_app

    store, item = linked_store(tmp_path)
    db, images = tmp_path / "b4.sqlite3", tmp_path / "images"
    try:
        revision = store.get_issue_record("issue").state_revision
    finally:
        store.db.close()
    app = create_app(ApiSettings(store_path=db, image_root=images, origin=ORIGIN, local_http=True,
        session_secret=SIGNING, service_token=TOKEN))
    headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "classify",
               "X-Steward-Expected-Revision": str(revision)}
    classification = {"signal_id": item.id, "category": "bulky_waste", "primary_target": "couch",
        "full_cleanup_scope": "couch and bags", "marked_work_area": "sidewalk", "large_object_count": 1}
    with TestClient(app, base_url=ORIGIN) as client:
        saved = client.post("/api/issues/issue/classification", headers=headers, json=classification)
        replay = client.post("/api/issues/issue/classification", headers=headers, json=classification)
        conflict = client.post("/api/issues/issue/classification", headers=headers,
            json={**classification, "category": "litter"})
    assert saved.status_code == 200 and replay.json() == saved.json()
    assert conflict.status_code == 409
    classification_id = saved.json()["data"]["record_id"]
    with Store(db) as reopened:
        assert reopened.get_classification_fact(classification_id).provenance == "seeded"


def test_intake_vision_contract_defines_hazards_as_specialist_conditions():
    """Ordinary bulky waste must not be reported as a retained hazard by the photo inspector."""
    from agent.investigation import INTAKE_SYSTEM_PROMPT

    assert "visible_hazards" in INTAKE_SYSTEM_PROMPT and "not hazards" in INTAKE_SYSTEM_PROMPT
    description = c.IntakePhotoFindings.model_fields["visible_hazards"].description or ""
    assert "specialist" in description and "litter" in description
    assert "unknowns" in INTAKE_SYSTEM_PROMPT and "not unknowns" in INTAKE_SYSTEM_PROMPT
    unknowns = c.IntakePhotoFindings.model_fields["unknowns"].description or ""
    assert "extent" in unknowns and "bag" in unknowns
