"""B13 safe read projections use persisted API-owned records only."""

import sys

from test_dispatch import create_plan, dispatch
from test_investigation import ORIGIN
from test_investigation_repair import client_for, headers, photo

from agent import contracts as c
from agent.actors import AccessBoundary
from agent.foundation import main as foundation_main
from agent.read_views import issue_timeline
from agent.store import Store


def _dispatched(path):
    plan_id, revision = create_plan(path)
    with client_for(path) as client:
        result = dispatch(client, plan_id, revision, key="read-dispatch")
        assert result.status_code == 201, result.text
        return result.json()["data"]["record_id"]


def test_timeline_projects_only_persisted_signal_link_score(tmp_path, monkeypatch):
    path = tmp_path / "foundation.sqlite3"
    monkeypatch.setattr(sys, "argv", ["foundation", "--db", str(path)])
    assert foundation_main() == 0
    actor = c.ActorContext(actor_id="steward-service", actor_type="service", label="Steward",
                           district_id="south_loop_demo")
    with Store(path) as store:
        events = issue_timeline(store, AccessBoundary(actor, "south_loop_demo"), "demo-couch", limit=50).events
    linked = [event for event in events if event.type == "SIGNAL_LINKED"]
    assert [event.evidence_score for event in linked] == [85, 65]
    assert all(event.evidence_components is not None for event in linked)
    assert all(event.evidence_ids == () for event in linked)


def test_exception_snapshot_counts_use_event_time_status_not_mutable_column(tmp_path):
    from test_settlement import real_exception

    _job, _proof, exception_id, _choice = real_exception(tmp_path, chosen=True)
    with Store(tmp_path / "b4.sqlite3") as store:
        raised_id = next(event["id"] for event in store.events("issue")
                         if event["event_type"] == "EXCEPTION_RAISED"
                         and event["payload"].get("exception_id") == exception_id)
        _rows, _events, _records, counts = store.exception_snapshot_rows(
            after_rowid=0, limit=50, event_watermark=raised_id, row_watermark=None,
            statuses=("PENDING", "DECIDED"))
    assert counts == {"PENDING": 1}


def test_issue_detail_board_and_crew_discovery_are_safe_api_projections(tmp_path):
    job_id = _dispatched(tmp_path)
    with client_for(tmp_path) as client:
        detail = client.get("/api/issues/issue", headers=headers("read-detail"))
        assert detail.status_code == 200, detail.text
        payload = detail.json()["data"]
        assert payload["issue"]["id"] == "issue"
        assert payload["current"]["job"]["id"] == job_id
        assert payload["current"]["plan"]["quote_cents"] == 7200
        assert payload["current"]["next_actor"] == "crew"
        assert payload["current"]["allowed_next"] == ["accept_job"]
        assert payload["sources"]["items"]
        assert "image_ref" not in detail.text and "image_sha256" not in detail.text

        board = client.get("/api/board", headers=headers("read-board"))
        assert board.status_code == 200, board.text
        assert board.json()["data"]["budget"] == {
            "budget_id": "south_loop_demo", "initial_cents": 50000,
            "reserved_cents": 7200, "spent_cents": 0, "available_cents": 42800,
        }
        marker = next(item for item in board.json()["data"]["markers"] if item["issue_id"] == "issue")
        assert marker["status"] == "RESOLUTION_ACTIVE" and marker["marker_state"] != "resolved"
        assert marker["latitude"] == 41.86 and marker["longitude"] == -87.63

        assert client.get("/api/crew/jobs", headers=headers("crew-list")).status_code == 403
        selected = client.post("/api/demo/persona", headers={
            "Origin": ORIGIN, "X-Steward-Request": "1", "Idempotency-Key": "crew-select",
        }, json={"persona_id": "crew-south_loop_services"})
        assert selected.status_code == 200
        crew_jobs = client.get("/api/crew/jobs")
        assert crew_jobs.status_code == 200, crew_jobs.text
        assert crew_jobs.json()["data"]["jobs"][0]["id"] == job_id


def test_issue_detail_exposes_saved_official_conflict_without_claiming_a_lookup(tmp_path):
    _dispatched(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        store.record_service_match("issue", {
            "id": "official-completed-record", "status": "COMPLETED", "provenance": "seeded",
            "completed_at": "2026-01-01T00:00:00Z",
        })
    with client_for(tmp_path) as client:
        response = client.get("/api/issues/issue", headers=headers("official-state"))
        assert response.status_code == 200, response.text
        facts = response.json()["data"]["facts"]
        assert facts["official_conflict_record_id"] == "official-completed-record"
        assert facts["official_record_status"] == "COMPLETED"
        assert facts["official_conflict_state"] == "pending"
        assert facts["official_completed_at"] == "2026-01-01T00:00:00Z"


def test_receipt_evidence_and_content_follow_saved_canonical_association(tmp_path):
    with Store(tmp_path / "b4.sqlite3") as store:
        linked = photo(store, tmp_path, "linked")
        unlinked = photo(store, tmp_path, "unlinked")
        store.create_issue("issue", "unclassified", linked.reported_location)
        store.link_signal("issue", linked.id)
        evidence_id = store.evidence_for_entity(signal_id=linked.id)[0].id
        expected = (tmp_path / "images" / f"{store.get_evidence(evidence_id).image_ref}.jpg").read_bytes()
        assert store.get_signal_receipt(linked.id).invocation_id is None
        assert store.invocation_for_signal(linked.id) is not None
        unlinked_evidence = store.evidence_for_entity(signal_id=unlinked.id)[0].id
    with client_for(tmp_path) as client:
        receipt = client.get(f"/api/signals/{linked.id}/receipt", headers=headers("receipt"))
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["data"]["invocation_id"]
        assert receipt.json()["data"]["processing"] == "PENDING"
        metadata = client.get(f"/api/evidence/{evidence_id}", headers=headers("evidence"))
        assert metadata.status_code == 200 and metadata.json()["data"]["role"] == "intake"
        body = client.get(f"/api/evidence/{evidence_id}/content", headers=headers("content"))
        assert body.status_code == 200 and body.content == expected
        assert body.headers["content-type"].startswith("image/jpeg")
        assert client.get(f"/api/evidence/{unlinked_evidence}", headers=headers("foreign")).status_code == 404


def test_issue_source_cursor_has_immutable_membership_and_rejects_invalid_shape(tmp_path):
    _dispatched(tmp_path)
    with client_for(tmp_path) as client:
        first = client.get("/api/issues/issue", params={"sources_limit": 1}, headers=headers("source-page"))
        assert first.status_code == 200, first.text
        page = first.json()["data"]["sources"]
        assert page["truncated"] is True and page["next_cursor"]
        first_id = page["items"][0]["id"]
        second = client.get("/api/issues/issue", params={"sources_limit": 1,
            "sources_cursor": page["next_cursor"]}, headers=headers("source-page-two"))
        assert second.status_code == 200, second.text
        assert second.json()["data"]["sources"]["items"][0]["id"] != first_id
        assert client.get("/api/issues/issue", params={"sources_cursor": "not-a-cursor"},
                          headers=headers("invalid-page")).status_code == 422


def test_issue_detail_retains_structured_historical_completion_results(tmp_path):
    from test_settlement import inspected_job

    job_id, submission_id = inspected_job(tmp_path, partial=True)
    with client_for(tmp_path) as client:
        detail = client.get("/api/issues/issue", headers=headers("completion-history"))
        assert detail.status_code == 200, detail.text
        history = detail.json()["data"]["evidence"]["history"]
        assert history["items"] == [{
            "submission_id": submission_id, "job_id": job_id,
            "verification_id": history["items"][0]["verification_id"],
            "before_evidence_id": history["items"][0]["before_evidence_id"],
            "after_evidence_id": history["items"][0]["after_evidence_id"],
            "submitted_at": history["items"][0]["submitted_at"],
            "findings": history["items"][0]["findings"],
            "components": history["items"][0]["components"],
            "total": 90,
            "prerequisites": history["items"][0]["prerequisites"],
            "unmet": ["area_clear"], "accepted": False,
        }]
        assert history["items"][0]["findings"]["area_clear"] is False
        assert history["items"][0]["components"]["area_clear"] == 0
