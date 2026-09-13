"""Consumer-visible regressions for the independently reproduced B4 failures."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event

import pytest
from fastapi.testclient import TestClient
from test_investigation import (
    ACTOR,
    AT,
    ORIGIN,
    SIGNING,
    TOKEN,
    context,
    facts,
    linked_store,
    signal,
)

from agent import contracts as c
from agent import investigation as inv
from agent.adapters import GeocodeResult, ServiceResult
from agent.api import create_app
from agent.config import ApiSettings
from agent.images import NormalizedImage
from agent.intake import persist_signal, resident_signal
from agent.store import Store


def client_for(path, **kwargs):
    return TestClient(create_app(ApiSettings(store_path=path / "b4.sqlite3",
        image_root=path / "images", origin=ORIGIN, local_http=True,
        session_secret=SIGNING, service_token=TOKEN), **kwargs), base_url=ORIGIN)


def headers(key, revision=None):
    values = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": key}
    if revision is not None:
        values["X-Steward-Expected-Revision"] = str(revision)
    return values


def photo(store, path, name="one", body=b"stored-jpeg", provenance="synthetic"):
    image = NormalizedImage(body, hashlib.sha256(body).hexdigest(), "2" * 16)
    actor = ACTOR.model_copy(update={"actor_type": "resident", "actor_id": name})
    item = resident_signal(actor=actor, idempotency_key=name, description="couch",
        location="1530 S Michigan Ave", received_at=AT, observed_at=AT,
        image=image, provenance=provenance)
    persist_signal(store, signal=item, context=c.MutationContext(actor=actor,
        operation="submit_signal", idempotency_key=name), image=image,
        image_root=path / "images", provenance=provenance)
    return item


def proposal(store, item, key, **changes):
    revision = store.get_issue_record("issue").state_revision
    fact = c.ClassificationFact(id=key, issue_id="issue", signal_id=item.id,
        category="bulky_waste", source_issue_revision=revision, provenance="seeded",
        proposed_by=ACTOR, created_at=datetime.now(UTC), **changes)
    return inv.save_classification(store, fact, context=context("save_classification", key, revision))[0]


@pytest.mark.parametrize("status", ["RESOLVED", "DUPLICATE", "INVALID", "RESOLUTION_ACTIVE"])
def test_saved_monitor_cannot_reopen_or_replace_workflow(tmp_path, status):
    with linked_store(tmp_path)[0] as store:
        revision = store.get_issue_record("issue").state_revision
        saved = inv.decide(store, issue_id="issue", proposed_type="MONITOR", summary="wait",
            evidence_ids=(), context=context("decide", "d", revision))
        store.db.execute("UPDATE issues SET status=? WHERE id='issue'", (status,))
        store.db.commit()
        with pytest.raises(ValueError):
            inv.apply_investigation_decision(store, issue_id="issue", decision_id=saved.id,
                context=context("apply", "apply", revision))
        assert store.get_issue_record("issue").status == status


def test_hazards_and_compatible_authority_survive_benign_replacement(tmp_path):
    with linked_store(tmp_path)[0] as store:
        item = store.get_signal("first")
        facts(store, item, hazards=("electrical",))
        other = signal("new", image=False)
        store.store_signal(other, actor=ACTOR)
        store.link_signal("issue", other.id)
        proposal(store, other, "benign")
        current = store.current_issue_facts("issue")
        assert "electrical" in current.unresolved_hazards
        assert current.hazard_sources
        assert current.jurisdiction is None


def test_http_fact_versions_and_mixed_provenance(tmp_path):
    with Store(tmp_path / "b4.sqlite3") as store:
        image_signal = photo(store, tmp_path)
        store.create_issue("issue", "unclassified", image_signal.reported_location)
        store.link_signal("issue", image_signal.id)
        live = replace(signal("live", image=False), provenance="live")
        store.store_signal(live, actor=ACTOR)
        store.link_signal("issue", live.id)
        evidence = store.evidence_for_entity(signal_id=image_signal.id)[0]
        revision = store.get_issue_record("issue").state_revision
    body = {"signal_id": live.id, "category": "bulky_waste", "supporting_evidence_ids": [evidence.id]}
    with client_for(tmp_path) as client:
        assert client.post("/api/issues/issue/classification", headers=headers("missing"), json=body).status_code == 422
        first = client.post("/api/issues/issue/classification", headers=headers("a", revision), json=body)
        second = client.post("/api/issues/issue/classification", headers=headers("b", revision + 1),
            json={**body, "primary_target": "couch"})
        assert first.status_code == second.status_code == 200
        assert client.post("/api/issues/issue/classification", headers=headers("a", revision), json=body).json() == first.json()
    with Store(tmp_path / "b4.sqlite3") as store:
        current = store.current_issue_facts("issue").classification
        assert current.id == second.json()["data"]["record_id"]
        assert current.fact_version == 2 and current.provenance == "synthetic"


def test_latest_negative_lookup_clears_credit_and_survives_restart(tmp_path):
    with linked_store(tmp_path)[0] as store:
        inv.record_service_lookup(store, issue_id="issue", signal_id="first",
            result=ServiceResult("MATCH", "311", "OPEN"), context=context("lookup", "first"))
        other = signal("other", image=False)
        store.store_signal(other, actor=ACTOR)
        store.link_signal("issue", other.id)
        inv.record_service_lookup(store, issue_id="issue", signal_id=other.id,
            result=ServiceResult("NO_MATCH"), context=context("lookup", "other"))
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_issue_record("issue").components.service_match == 0
        assert store.get_issue("issue")["service_record"] is None
        assert len(store.service_lookups_for_issue("issue")) == 2


def test_adapter_output_changes_do_not_change_identical_request(tmp_path):
    with linked_store(tmp_path)[0] as store:
        ctx = context("geocode", "first")
        first = inv.record_geocode(store, issue_id="issue", signal_id="first",
            result=GeocodeResult("NO_MATCH", None), context=ctx)
        replay = inv.record_geocode(store, issue_id="issue", signal_id="first",
            result=GeocodeResult("UNAVAILABLE", None), context=ctx)
        assert first == replay


def test_decision_http_replay_and_cause_are_immutable(tmp_path):
    with linked_store(tmp_path)[0] as store:
        revision = store.get_issue_record("issue").state_revision
    body = {"decision_type": "MONITOR", "summary": "wait", "evidence_ids": []}
    with client_for(tmp_path) as client:
        first = client.post("/api/issues/issue/decisions", headers=headers("d", revision), json=body)
        assert first.status_code == 200
        client.post("/api/issues/issue/investigation-action", headers=headers("a", revision),
            json={"decision_id": first.json()["data"]["record_id"]})
        again = client.post("/api/issues/issue/decisions", headers=headers("d", revision), json=body)
        assert first.json() == again.json()
    with Store(tmp_path / "b4.sqlite3") as store:
        decision = store.get_decision(first.json()["data"]["record_id"])
        assert decision.trigger_event_id not in first.json()["event_ids"]
        assert store.get_event(decision.trigger_event_id).event_type == "INVESTIGATION_REQUESTED"


def test_related_candidates_filter_before_limit(tmp_path):
    with Store(tmp_path / "b4.sqlite3") as store:
        store.store_signal(signal("source"), actor=ACTOR)
        for i in range(23):
            store.store_signal(replace(signal(f"a{i:02}"), reported_location="elsewhere"), actor=ACTOR)
        store.store_signal(signal("z-match", image=False), actor=ACTOR)
    with client_for(tmp_path) as client:
        response = client.get("/api/signals/related", params={"signal_id": "source"}, headers=headers("read"))
        assert "z-match" in [x["id"] for x in response.json()["data"]["candidates"]]


def test_failed_inspection_replays_error_but_new_key_recovers(tmp_path, monkeypatch):
    def fail(_):
        raise RuntimeError("transient")
    with Store(tmp_path / "b4.sqlite3") as store:
        item = photo(store, tmp_path)
        args = {"signal_id": item.id, "image_root": tmp_path / "images"}
        failed = inv.inspect_intake_photo(store, **args, inspector=fail, context=context("inspect", "old"))
        assert failed.outcome == "ERROR" and failed.event_ids
    monkeypatch.setattr(inv, "settings", replace(inv.settings, vision_model_id="different"))
    with Store(tmp_path / "b4.sqlite3") as store:
        assert inv.inspect_intake_photo(store, **args, inspector=fail, context=context("inspect", "old")) == failed
        good = inv.inspect_intake_photo(store, **args, inspector=lambda _: c.IntakePhotoFindings(),
            context=context("inspect", "new"))
        assert good.outcome == "OK" and good.data.record_id != failed.data.record_id


def test_cache_association_stays_on_requesting_issue_and_hazards(tmp_path):
    calls = []
    with Store(tmp_path / "b4.sqlite3") as store:
        for name in ("one", "two"):
            item = photo(store, tmp_path, name)
            store.create_issue(name, "bulky_waste", item.reported_location)
            store.link_signal(name, item.id)
            result = inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
                inspector=lambda _: calls.append(1) or c.IntakePhotoFindings(visible_hazards=("electrical",)),
                context=context("inspect", name))
            saved = store.get_intake_inspection(result.data.record_id)
            assert saved.signal_id == item.id
            current = store.current_issue_facts(name)
            assert current.intake_inspections and "electrical" in current.unresolved_hazards
        assert calls == [1]


def test_concurrent_inspection_claim_never_duplicates_inference(tmp_path):
    path = tmp_path / "b4.sqlite3"
    with Store(path) as store:
        item = photo(store, tmp_path)
    entered, release = Event(), Event()
    calls = []
    def inspect(_):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return c.IntakePhotoFindings()
    def run(key):
        with Store(path) as store:
            return inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
                inspector=inspect, context=context("inspect", key))
    with ThreadPoolExecutor(2) as executor:
        first = executor.submit(run, "key")
        assert entered.wait(5)
        try:
            second = executor.submit(run, "key").result(timeout=2)
            assert second.outcome == "ERROR" and second.reason_code == "INSPECTION_IN_PROGRESS"
            assert calls == [1]
        finally:
            release.set()
        assert first.result().outcome == "OK"


def test_hazard_free_replacement_requires_new_jurisdiction_and_real_versions(tmp_path):
    with linked_store(tmp_path)[0] as store:
        item = store.get_signal("first")
        facts(store, item)
        changed = proposal(store, item, "changed", primary_target="different couch")
        assert changed.fact_version == 3
        assert store.current_issue_facts("issue").jurisdiction is None
        old = store.get_jurisdiction_fact("jurisdiction")
        revision = store.get_issue_record("issue").state_revision
        with pytest.raises(ValueError, match="current classification"):
            inv.save_jurisdiction(store, old.model_copy(update={"id": "stale",
                "source_issue_revision": revision}), context=context("jurisdiction", "stale", revision))
        fresh, _ = inv.save_jurisdiction(store, old.model_copy(update={"id": "fresh",
            "classification_fact_id": changed.id, "source_issue_revision": revision}),
            context=context("jurisdiction", "fresh", revision))
        assert fresh.fact_version == 4
        assert store.current_issue_facts("issue").jurisdiction == fresh


def test_hazard_blocks_action_even_with_fresh_benign_authority(tmp_path):
    with linked_store(tmp_path)[0] as store:
        item = store.get_signal("first")
        facts(store, item, hazards=("electrical",))
        changed = proposal(store, item, "benign")
        revision = store.get_issue_record("issue").state_revision
        old = store.get_jurisdiction_fact("jurisdiction")
        inv.save_jurisdiction(store, old.model_copy(update={"id": "fresh",
            "classification_fact_id": changed.id, "source_issue_revision": revision}),
            context=context("jurisdiction", "fresh", revision))
        store.record_geocode("issue", accuracy_m=10, provenance="seeded")
        store.add_signal("issue", signal("witness", author="other", image=False, text="Another report"))
        revision = store.get_issue_record("issue").state_revision
        with pytest.raises(ValueError, match="MARK_ACTIONABLE gate failed"):
            inv.decide(store, issue_id="issue", proposed_type="MARK_ACTIONABLE", summary="clean",
                evidence_ids=(), context=context("decide", "blocked", revision))
        assert store.current_issue_facts("issue").unresolved_hazards == ("electrical",)


def test_actual_http_scope_blocks_foreign_records_and_filters_candidates(tmp_path):
    from test_api_auth import seed_boundary_records

    path = tmp_path / "b4.sqlite3"
    seed_boundary_records(path)
    with Store(path) as store:
        unlinked = photo(store, tmp_path, "foreign-photo")
        store.link_signal("foreign", unlinked.id)  # Retains its signal-only evidence association.
        store.store_signal(signal("search", image=False), actor=ACTOR)
        revision = store.get_issue_record("foreign").state_revision
    def forbidden(_):
        pytest.fail("foreign inspection reached the inspector")
    with client_for(tmp_path, intake_inspector=forbidden) as client:
        for suffix, body in (
            ("decisions", {"decision_type": "MONITOR", "summary": "wait"}),
            ("classification", {"signal_id": unlinked.id, "category": "litter"}),
            ("geocode", {"signal_id": unlinked.id}),
            ("service-records/search", {"signal_id": unlinked.id}),
            ("investigation-action", {"decision_id": "missing"}),
        ):
            response = client.post(f"/api/issues/foreign/{suffix}", headers=headers(suffix.replace("/", "-"), revision), json=body)
            assert response.status_code == 404, response.text
        assert client.post(f"/api/signals/{unlinked.id}/intake-inspection", headers=headers("inspect")).status_code == 404
        assert client.get("/api/signals/related", params={"signal_id": unlinked.id}, headers=headers("q")).status_code == 404
        related = client.get("/api/signals/related", params={"signal_id": "search"}, headers=headers("q"))
        assert unlinked.id not in {x["id"] for x in related.json()["data"]["candidates"]}
        similar = client.get("/api/issues/similar", params={"signal_id": "search"}, headers=headers("q"))
        assert {x["id"] for x in similar.json()["data"]["candidates"]} == {"one", "two"}


def test_direct_operation_scope_is_enforced_before_saved_replay(tmp_path):
    from agent.actors import AccessError

    with linked_store(tmp_path)[0] as store:
        revision = store.get_issue_record("issue").state_revision
        ctx = context("decide", "saved", revision)
        inv.decide(store, issue_id="issue", proposed_type="MONITOR", summary="wait", evidence_ids=(), context=ctx)
        with store.transaction() as tx:
            tx.insert_plan(c.PlanRecord(id="foreign", issue_id="issue", district_id="other",
                service_type="bulky_waste", condition="couch", scope="couch", work_area="sidewalk",
                required_equipment=("truck",), crew_count=2, quote_cents=7200,
                policy_version="south-loop-v3", created_at=AT))
        with pytest.raises(AccessError) as error:
            inv.decide(store, issue_id="issue", proposed_type="MONITOR", summary="wait", evidence_ids=(), context=ctx)
        assert error.value.status == 404


def expire_claim(store, context_):
    from datetime import timedelta

    claim = store.intake_claim_for_request(context_)
    expired = claim.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    store.db.execute("UPDATE intake_inspection_claims SET record_json=?, expires_at=? WHERE id=?",
        (expired.model_dump_json(), expired.expires_at.isoformat(), expired.id))
    store.db.commit()


def test_crashed_claim_reopens_as_unknown_error_and_new_key_can_recover(tmp_path):
    class Crash(BaseException):
        pass
    def crash(_):
        raise Crash()
    ctx = context("inspect", "crash")
    with Store(tmp_path / "b4.sqlite3") as store:
        item = photo(store, tmp_path)
        with pytest.raises(Crash):
            inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images", inspector=crash, context=ctx)
        assert store.intake_claim_for_request(ctx).status == "RUNNING"
        expire_claim(store, ctx)
    with Store(tmp_path / "b4.sqlite3") as store:
        result = inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images", inspector=crash, context=ctx)
        assert result.reason_code == "INSPECTION_INTERRUPTED" and result.outcome == "ERROR"
        assert store.get_intake_inspection(result.data.record_id).metadata is None
        recovered = inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
            inspector=lambda _: c.IntakePhotoFindings(), context=context("inspect", "recover"))
        assert recovered.outcome == "OK"
        assert store.get_intake_claim(store.get_intake_inspection(recovered.data.record_id).claim_id).status == "FINISHED"


def test_different_key_cache_race_and_fenced_late_result_retains_attempt(tmp_path):
    path = tmp_path / "b4.sqlite3"
    with Store(path) as store:
        item = photo(store, tmp_path)
    entered, release = Event(), Event()
    def slow(_):
        entered.set()
        assert release.wait(5)
        return {"findings": c.IntakePhotoFindings(visible_objects=("old",)),
                "usage": {"inputTokens": 23, "outputTokens": 5}}
    def run():
        with Store(path) as store:
            return inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
                inspector=slow, context=context("inspect", "old"))
    with ThreadPoolExecutor(1) as worker:
        pending = worker.submit(run)
        assert entered.wait(5)
        try:
            with Store(path) as store:
                busy = inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
                    inspector=lambda _: pytest.fail("busy cache invoked"), context=context("inspect", "new"))
                assert busy.reason_code == "INSPECTION_IN_PROGRESS"
                expire_claim(store, context("inspect", "old"))
                good = inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
                    inspector=lambda _: c.IntakePhotoFindings(visible_objects=("new",)), context=context("inspect", "new"))
                assert good.outcome == "OK"
        finally:
            release.set()
        assert pending.result().reason_code == "INSPECTION_INTERRUPTED"
    with Store(path) as store:
        records = store.intake_inspections_for_signal(item.id)
        late = next(r for r in records if r.metadata and r.metadata.usage)
        assert late.metadata.usage.inputTokens == 23 and not late.cache_eligible
        cached = store.find_intake_inspection(late.cache_key)
        assert cached.findings.visible_objects == ("new",)


def test_same_config_error_recovery_and_http_error_receipt(tmp_path):
    with Store(tmp_path / "b4.sqlite3") as store:
        item = photo(store, tmp_path)
    count = []
    def flaky(_):
        count.append(1)
        if len(count) == 1:
            raise RuntimeError("offline transient")
        return c.IntakePhotoFindings(visible_objects=("couch",))
    with client_for(tmp_path, intake_inspector=flaky) as client:
        path = f"/api/signals/{item.id}/intake-inspection"
        failed = client.post(path, headers=headers("old"))
        replay = client.post(path, headers=headers("old"))
        good = client.post(path, headers=headers("new"))
        assert failed.status_code == replay.status_code == 503
        assert failed.json() == replay.json() and failed.json()["event_ids"]
        assert good.status_code == 200 and count == [1, 1]


def test_concurrent_fact_proposals_use_cas_and_preserve_versions(tmp_path):
    from agent.store import RevisionConflict

    with linked_store(tmp_path)[0] as store:
        revision = store.get_issue_record("issue").state_revision
    def run(key):
        with Store(tmp_path / "b4.sqlite3") as store:
            fact = c.ClassificationFact(id=key, issue_id="issue", signal_id="first", category="bulky_waste",
                source_issue_revision=revision, provenance="seeded", proposed_by=ACTOR, created_at=AT)
            try:
                return inv.save_classification(store, fact, context=context("classify", key, revision))[0]
            except RevisionConflict:
                return None
    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(run, ("one", "two")))
    assert sum(r is not None for r in results) == 1
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.current_issue_facts("issue").classification.fact_version == 1
        assert store.get_issue_record("issue").state_revision == revision + 1


def test_http_jurisdiction_updates_versions_and_inherits_all_support_origins(tmp_path):
    with Store(tmp_path / "b4.sqlite3") as store:
        item = photo(store, tmp_path)
        store.create_issue("issue", "unclassified", item.reported_location)
        store.link_signal("issue", item.id)
        live = replace(signal("live", image=False), provenance="live")
        store.store_signal(live, actor=ACTOR)
        store.link_signal("issue", live.id)
        evidence_id = store.evidence_for_entity(signal_id=item.id)[0].id
        revision = store.get_issue_record("issue").state_revision
    with client_for(tmp_path) as client:
        first = client.post("/api/issues/issue/classification", headers=headers("c1", revision),
            json={"signal_id": live.id, "category": "bulky_waste", "supporting_evidence_ids": [evidence_id]})
        classification_id = first.json()["data"]["record_id"]
        body = {"classification_fact_id": classification_id, "responsibility": "district"}
        first_j = client.post("/api/issues/issue/jurisdiction", headers=headers("j1", revision + 1), json=body)
        second_j = client.post("/api/issues/issue/jurisdiction", headers=headers("j2", revision + 2),
            json={**body, "responsibility": "unknown"})
        assert first_j.status_code == second_j.status_code == 200
        assert client.post("/api/issues/issue/jurisdiction", headers=headers("j1", revision + 1), json=body).json() == first_j.json()
        second_c = client.post("/api/issues/issue/classification", headers=headers("c2", revision + 3),
            json={"signal_id": item.id, "category": "bulky_waste", "supporting_evidence_ids": [evidence_id]})
        assert second_c.status_code == 200
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_jurisdiction_fact(second_j.json()["data"]["record_id"]).provenance == "synthetic"
        assert store.current_issue_facts("issue").classification.fact_version == 4
        assert store.current_issue_facts("issue").jurisdiction is None


def test_replay_never_runs_a_changed_adapter(tmp_path):
    with linked_store(tmp_path)[0]:
        pass
    class Adapters:
        broken = False
        def geocode(self, _):
            assert not self.broken, "replay called changed adapter"
            return GeocodeResult("NO_MATCH", None)
    adapter = Adapters()
    with client_for(tmp_path, adapters=adapter) as client:
        first = client.post("/api/issues/issue/geocode", headers=headers("geo"), json={"signal_id": "first"})
        adapter.broken = True
        replay = client.post("/api/issues/issue/geocode", headers=headers("geo"), json={"signal_id": "first"})
        assert first.status_code == replay.status_code == 200
        assert first.json() == replay.json()


@pytest.mark.parametrize("outcome", ["NO_MATCH", "UNAVAILABLE"])
def test_current_negative_geocode_revokes_precision_and_negative_lookup_revokes_match(tmp_path, outcome):
    with linked_store(tmp_path)[0] as store:
        inv.record_geocode(store, issue_id="issue", signal_id="first",
            result=GeocodeResult("MATCH", c.LocationRecord(lat=41.86102, lon=-87.62406, accuracy_m=10, provenance="seeded")),
            context=context("geo", "first"))
        inv.record_service_lookup(store, issue_id="issue", signal_id="first", result=ServiceResult("MATCH", "r", "OPEN"),
            context=context("lookup", "first"))
        other = signal("other", image=False)
        store.store_signal(other, actor=ACTOR)
        store.link_signal("issue", other.id)
        revision = store.get_issue_record("issue").state_revision
        inv.record_geocode(store, issue_id="issue", signal_id=other.id, result=GeocodeResult(outcome, None),
            context=context("geo", "other"))
        inv.record_service_lookup(store, issue_id="issue", signal_id=other.id, result=ServiceResult(outcome),
            context=context("lookup", "other"))
        current = store.get_issue_record("issue")
        assert current.components.precise_geocode == current.components.service_match == 0
        assert current.state_revision == revision + 2
        assert store.current_issue_facts("issue").geocode.outcome == outcome
        assert store.latest_service_lookup("issue").outcome == outcome


def test_schema_three_attempt_bytes_survive_four_and_failed_upgrade_is_atomic(tmp_path, monkeypatch):
    import sqlite3

    from agent import migrations

    path = tmp_path / "b4.sqlite3"
    with Store(path) as store:
        item = photo(store, tmp_path)
        result = inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
            inspector=lambda _: c.IntakePhotoFindings(), context=context("inspect", "saved"))
        record = store.get_intake_inspection(result.data.record_id)
        raw = record.model_dump_json(exclude={"cached_from_id", "claim_id", "cache_eligible", "profile", "model_id", "region"})
    # Construct the actual previous schema around saved records, only in this temporary DB.
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE intake_inspection_claims")
        db.execute("DROP TABLE intake_inspections")
        db.execute("CREATE TABLE intake_inspections (record_json TEXT NOT NULL, " + migrations.FACT_TABLES["intake_inspections"] + ")")
        db.execute("INSERT INTO intake_inspections VALUES (?,?,?,?,?)", (raw, record.id, item.id, record.evidence_id, record.cache_key))
        migrations._immutable(db, "intake_inspections")
        db.execute("CREATE INDEX intake_inspections_signal ON intake_inspections(signal_id,id)")
        db.execute("PRAGMA user_version=3")
    upgrade = migrations._upgrade_four
    def fail(db):
        upgrade(db)
        raise RuntimeError("injected migration failure")
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "_upgrade_four", fail)
        with pytest.raises(RuntimeError, match="injected"):
            Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT record_json FROM intake_inspections").fetchone()[0] == raw
    with Store(path) as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert store.db.execute("SELECT record_json FROM intake_inspections").fetchone()[0] == raw
        assert store.get_intake_inspection(record.id).findings == record.findings
        assert store.find_intake_inspection(record.cache_key) is None  # missing full old basis is not qualified cache
        assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_real_saved_invocation_cause_is_validated_before_replay(tmp_path):
    with linked_store(tmp_path)[0] as store:
        store.create_issue("foreign-cause", "litter", "elsewhere")
        invocations = []
        with store.transaction() as tx:
            for issue_id in ("issue", "foreign-cause"):
                trigger = tx.append_event(c.NewEvent(issue_id=issue_id, event_type="SIGNAL_RECEIVED",
                    timestamp=AT, actor=ACTOR, policy_version="south-loop-v3", payload=c.EventFacts()))
                invocations.append(tx.insert_pending_invocation(c.PendingInvocationSpec(id=issue_id,
                    trigger_type="SIGNAL_RECEIVED", policy_version="south-loop-v3"), trigger))
        revision = store.get_issue_record("issue").state_revision
        ctx = context("decide", "cause", revision).model_copy(update={"invocation_id": "issue"})
        saved = inv.decide(store, issue_id="issue", proposed_type="MONITOR", summary="wait", evidence_ids=(), context=ctx)
        assert saved.trigger_event_id == invocations[0].trigger_event_id
        assert saved.invocation_id == "issue" and saved.metadata is None
        bad = ctx.model_copy(update={"invocation_id": "foreign-cause"})
        with pytest.raises(ValueError, match="cause"):
            inv.decide(store, issue_id="issue", proposed_type="MONITOR", summary="wait", evidence_ids=(), context=bad)


def test_applied_dispute_survives_same_record_but_not_new_authoritative_record(tmp_path):
    with linked_store(tmp_path)[0] as store:
        completed_at = datetime(2026, 9, 11, tzinfo=UTC)
        result = ServiceResult("MATCH", "record", "COMPLETED", completed_at)
        inv.record_service_lookup(store, issue_id="issue", signal_id="first", result=result, context=context("lookup", "first"))
        second = signal("second", author="other", image=False, text="Another physical report")
        store.store_signal(second, actor=ACTOR)
        store.link_signal("issue", second.id)
        revision = store.get_issue_record("issue").state_revision
        decision = inv.decide(store, issue_id="issue", proposed_type="DISPUTE_OFFICIAL_STATUS", summary="two later reports",
            evidence_ids=(), context=context("decide", "dispute", revision))
        inv.apply_investigation_decision(store, issue_id="issue", decision_id=decision.id,
            context=context("apply", "dispute", revision))
        assert store.get_issue_record("issue").state_revision == revision + 1
        inv.record_service_lookup(store, issue_id="issue", signal_id=second.id, result=result, context=context("lookup", "second"))
        assert store.get_issue("issue")["service_record"]["conflict"] == "disputed"
        assert store.get_issue_record("issue").components.service_match == 15
        third = signal("third", author="third", image=False, text="Separate report")
        store.store_signal(third, actor=ACTOR)
        store.link_signal("issue", third.id)
        inv.record_service_lookup(store, issue_id="issue", signal_id=third.id,
            result=ServiceResult("MATCH", "different-record", "COMPLETED", completed_at), context=context("lookup", "third"))
        assert store.get_issue_record("issue").components.service_match == 0
        assert store.get_issue("issue")["service_record"]["conflict"] == "pending"


def test_failed_inspection_finalize_rolls_back_receipt_result_and_claim_finish(tmp_path, monkeypatch):
    from agent.store import StoreTransaction

    path = tmp_path / "b4.sqlite3"
    with Store(path) as store:
        item = photo(store, tmp_path)
        original = StoreTransaction.save_request
        def fail(tx, receipt):
            if receipt.operation == "inspect":
                raise RuntimeError("receipt write failed")
            return original(tx, receipt)
        with monkeypatch.context() as patch:
            patch.setattr(StoreTransaction, "save_request", fail)
            with pytest.raises(RuntimeError, match="receipt write failed"):
                inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
                    inspector=lambda _: c.IntakePhotoFindings(), context=context("inspect", "fail"))
        assert store.intake_inspections_for_signal(item.id) == []
        assert store.intake_claim_for_request(context("inspect", "fail")).status == "RUNNING"
        assert store.request_for_operation(context("inspect", "fail")) is None


def test_inspector_uses_frozen_model_profile_and_keeps_malformed_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "offline-profile-one")
    configured = inv.settings.resolved_vision_model_id
    def answer(_):
        monkeypatch.setattr(inv, "settings", replace(inv.settings, vision_model_id="later-model"))
        monkeypatch.setenv("AWS_PROFILE", "offline-profile-two")
        return {"findings": {"unexpected": "malformed"}, "usage": {"inputTokens": 12}, "request_id": "fake-receipt"}
    with Store(tmp_path / "b4.sqlite3") as store:
        item = photo(store, tmp_path)
        result = inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images", inspector=answer,
            context=context("inspect", "frozen"))
        saved = store.get_intake_inspection(result.data.record_id)
        assert result.outcome == "ERROR" and saved.error_code == "INVALID_MODEL_OUTPUT"
        assert saved.model_id == configured and saved.profile == "offline-profile-one"
        assert saved.metadata.usage.inputTokens == 12 and saved.metadata.request_id == "fake-receipt"
        assert saved.findings is None


def bound_b3_intake(store, tmp_path, name="cause-photo"):
    """Use actual B3 intake and the existing trusted Store binding operation."""
    item = photo(store, tmp_path, name)
    cause = store.get_event(store.get_signal_receipt(item.id).event_id)
    invocation = next(record for record in store.pending_invocations() if record.trigger_event_id == cause.id)
    assert cause.issue_id is None and cause.signal_id == invocation.signal_id == item.id
    created = inv.create_issue_from_signal(store, signal_id=item.id,
        rationale="new physical observation", context=context("create", name))
    issue_id = created.result.data.record_id
    with store.transaction() as tx:
        tx.replace_invocation(invocation.model_copy(update={"issue_id": issue_id,
            "state_revision": invocation.state_revision + 1}), invocation.state_revision)
    return item, cause, store.get_invocation(invocation.id), issue_id


def test_actual_b3_cause_survives_link_action_and_old_key_replay(tmp_path):
    with Store(tmp_path / "b4.sqlite3") as store:
        item, cause, invocation, issue_id = bound_b3_intake(store, tmp_path)
        original_cause = cause.model_dump_json()
        revision = store.get_issue_record(issue_id).state_revision
        ctx = context("decide", "actual-cause", revision).model_copy(update={"invocation_id": invocation.id})
        decision = inv.decide(store, issue_id=issue_id, proposed_type="MONITOR", summary="wait",
            evidence_ids=(), context=ctx)
        assert decision.trigger_event_id == cause.id
        assert decision.invocation_id == invocation.id
        assert cause.id not in store.request_for_operation(ctx).result.event_ids
        action_context = context("apply", "actual-cause", revision).model_copy(update={"invocation_id": invocation.id})
        action = inv.apply_investigation_decision(store, issue_id=issue_id, decision_id=decision.id,
            context=action_context)
        assert store.get_issue_record(issue_id).status == "MONITORING"
        assert store.issue_for_signal(item.id).id == issue_id
        assert inv.decide(store, issue_id=issue_id, proposed_type="MONITOR", summary="wait",
            evidence_ids=(), context=ctx) == decision
        assert inv.apply_investigation_decision(store, issue_id=issue_id, decision_id=decision.id,
            context=action_context) == action
        evidence_id = store.evidence_for_entity(signal_id=item.id)[0].id
        current_revision = store.get_issue_record(issue_id).state_revision
        classification = c.ClassificationFact(id="actual-classification", issue_id=issue_id, signal_id=item.id,
            category="bulky_waste", source_issue_revision=current_revision, supporting_evidence_ids=(evidence_id,),
            provenance="synthetic", proposed_by=ACTOR, created_at=AT)
        inv.save_classification(store, classification,
            context=context("classify", "actual", current_revision).model_copy(update={"invocation_id": invocation.id}))
        inspected = inv.inspect_intake_photo(store, signal_id=item.id, image_root=tmp_path / "images",
            inspector=lambda _: c.IntakePhotoFindings(visible_objects=("couch",)),
            context=context("inspect", "actual").model_copy(update={"invocation_id": invocation.id}))
        assert inspected.outcome == "OK"
        assert store.get_event(cause.id).model_dump_json() == original_cause


@pytest.mark.parametrize("corruption", ["target", "signal", "trigger", "trigger_type", "canonical_foreign", "contradictory_issue"])
def test_contradictory_actual_cause_is_rejected_before_decision_and_action_replay(tmp_path, corruption):
    with Store(tmp_path / "b4.sqlite3") as store:
        _, cause, invocation, issue_id = bound_b3_intake(store, tmp_path)
        other_signal, other_cause, _, other_issue = bound_b3_intake(store, tmp_path, "other-photo")
        revision = store.get_issue_record(issue_id).state_revision
        ctx = context("decide", "original", revision).model_copy(update={"invocation_id": invocation.id})
        decision = inv.decide(store, issue_id=issue_id, proposed_type="MONITOR", summary="wait", evidence_ids=(), context=ctx)
        action_ctx = context("apply", "original", revision).model_copy(update={"invocation_id": invocation.id})
        inv.apply_investigation_decision(store, issue_id=issue_id, decision_id=decision.id, context=action_ctx)
        with store.transaction() as tx:
            foreign_trigger = tx.append_event(c.NewEvent(**other_cause.model_dump(exclude={"id"})))
            contradictory = tx.append_event(c.NewEvent(**{**cause.model_dump(exclude={"id"}), "issue_id": other_issue}))
        changes = {"target": {"issue_id": other_issue}, "signal": {"signal_id": other_signal.id},
            "trigger": {"trigger_event_id": foreign_trigger.id}, "trigger_type": {"trigger_type": "PROOF_SUBMITTED"},
            "canonical_foreign": {"trigger_event_id": foreign_trigger.id, "signal_id": other_signal.id},
            "contradictory_issue": {"trigger_event_id": contradictory.id}}[corruption]
        corrupted = invocation.model_copy(update=changes)
        # Internal corruption fixture; no HTTP body can provide these runtime identities.
        store.db.execute("UPDATE invocations SET record_json=?,issue_id=?,signal_id=?,trigger_event_id=?,trigger_type=? WHERE id=?",
            (corrupted.model_dump_json(), corrupted.issue_id, corrupted.signal_id, corrupted.trigger_event_id,
             corrupted.trigger_type, corrupted.id))
        store.db.commit()
        with pytest.raises(ValueError, match="cause"):
            inv.decide(store, issue_id=issue_id, proposed_type="MONITOR", summary="wait", evidence_ids=(), context=ctx)
        with pytest.raises(ValueError, match="cause"):
            inv.apply_investigation_decision(store, issue_id=issue_id, decision_id=decision.id, context=action_ctx)
        assert store.get_issue_record(issue_id).status == "MONITORING"
        assert store.get_event(cause.id).issue_id is None
