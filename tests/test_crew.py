"""B6 crew workflow regressions, always starting with B5's real dispatch."""
from datetime import UTC, datetime, timedelta
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
from test_dispatch import create_plan, dispatch
from test_investigation import ORIGIN
from test_investigation_repair import client_for

from agent.store import Store


def crew_headers(key: str, revision: int):
    return {"Origin": ORIGIN, "X-Steward-Request": "1", "Idempotency-Key": key,
            "X-Steward-Expected-Revision": str(revision)}


def select_crew(client: TestClient, persona="crew-south_loop_services"):
    response = client.post("/api/demo/persona", headers={"Origin": ORIGIN,
        "X-Steward-Request": "1", "Idempotency-Key": "select-crew"}, json={"persona_id": persona})
    assert response.status_code == 200, response.text


def image_bytes(color):
    output = BytesIO()
    Image.new("RGB", (24, 24), color).save(output, format="JPEG")
    return output.getvalue()


def dispatched_job(path):
    plan, revision = create_plan(path)
    with client_for(path) as client:
        response = dispatch(client, plan, revision, key="crew-dispatch")
        assert response.status_code == 201, response.text
        return response.json()["data"]["record_id"]


def test_crew_accept_checkin_and_first_proof_are_durable_and_replay(tmp_path):
    job_id = dispatched_job(tmp_path)
    before, after = image_bytes("red"), image_bytes("green")
    claimed = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    with client_for(tmp_path) as client:
        select_crew(client)
        accepted = client.post(f"/api/jobs/{job_id}/accept", headers=crew_headers("accept", 0))
        assert accepted.status_code == 200, accepted.text
        assert client.post(f"/api/jobs/{job_id}/accept", headers=crew_headers("accept", 0)).json() == accepted.json()
        checked = client.post(f"/api/jobs/{job_id}/check-in", headers=crew_headers("check", 1), json={
            "latitude": 41.81, "longitude": -87.62, "accuracy_m": 999.0, "claimed_at": claimed})
        assert checked.status_code == 200, checked.text
        proof = client.post(f"/api/jobs/{job_id}/proof", headers=crew_headers("proof", 2), files={
            "before": ("before.jpg", before, "image/jpeg"),
            "after": ("after.jpg", after, "image/jpeg"),
            "metadata": (None, (
                '{"before_observed_at":"2026-09-12T00:00:00+00:00",'
                '"after_observed_at":"2026-09-13T00:00:00+00:00"}'))})
        assert proof.status_code == 202, proof.text
        assert proof.json()["data"]["state_revision"] == 3
        assert proof.json()["event_ids"]
        assert client.post(f"/api/jobs/{job_id}/proof", headers=crew_headers("proof", 2), files={
            "before": ("before.jpg", before, "image/jpeg"), "after": ("after.jpg", after, "image/jpeg"),
            "metadata": (None, (
                '{"before_observed_at":"2026-09-12T00:00:00+00:00",'
                '"after_observed_at":"2026-09-13T00:00:00+00:00"}'))}).json() == proof.json()
    with Store(tmp_path / "b4.sqlite3") as store:
        job = store.get_job(job_id)
        submission = store.get_submission(job.latest_submission_id)
        assert job.status == "PROOF_SUBMITTED" and job.current_verification_id is None
        assert job.checkin_claimed_at.isoformat() == claimed
        assert submission.job_revision == job.state_revision == 3
        assert submission.before_evidence_id != submission.after_evidence_id
        assert len(store.evidence_for_entity(job_id=job_id)) == 2
        event = store.get_event(proof.json()["event_ids"][0])
        assert event.event_type == "PROOF_SUBMITTED" and event.payload.submission_id == submission.id
        assert store.db.execute("SELECT COUNT(*) FROM invocations WHERE job_id=?", (job_id,)).fetchone()[0] == 1
        assert store.budget_availability("south_loop_demo").reserved_cents == 7200


def test_crew_scope_state_stale_and_changed_replay_are_rejected(tmp_path):
    job_id = dispatched_job(tmp_path)
    with client_for(tmp_path) as client:
        select_crew(client, "crew-windy_city_maintenance")
        assert client.post(f"/api/jobs/{job_id}/accept", headers=crew_headers("bad", 0)).status_code == 404
        select_crew(client)
        assert client.post(f"/api/jobs/{job_id}/check-in", headers=crew_headers("skip", 0), json={
            "latitude": 41.8, "longitude": -87.6}).status_code == 409
        assert client.post(f"/api/jobs/{job_id}/accept", headers=crew_headers("same", 9)).status_code == 409
        assert client.post(f"/api/jobs/{job_id}/accept", headers=crew_headers("same", 0)).status_code == 200
        # The same key is actor/operation scoped, and changing its expected job revision conflicts.
        assert client.post(f"/api/jobs/{job_id}/accept", headers=crew_headers("same", 1)).status_code == 409


def test_proof_rejects_bad_multipart_and_unknown_metadata_without_state(tmp_path):
    job_id = dispatched_job(tmp_path)
    with client_for(tmp_path) as client:
        select_crew(client)
        assert client.post(f"/api/jobs/{job_id}/accept", headers=crew_headers("a", 0)).status_code == 200
        assert client.post(f"/api/jobs/{job_id}/check-in", headers=crew_headers("c", 1), json={
            "latitude": 41.8, "longitude": -87.6}).status_code == 200
        response = client.post(f"/api/jobs/{job_id}/proof", headers=crew_headers("bad-meta", 2), files={
            "before": ("before.jpg", image_bytes("red"), "image/jpeg"),
            "after": ("after.jpg", image_bytes("green"), "image/jpeg"),
            "metadata": (None, '{"unknown":"no"}')})
        assert response.status_code == 422
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job_id).status == "CHECKED_IN"
        assert store.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 0


def test_proof_tracks_each_image_provenance_and_rework_retains_original_before(tmp_path, monkeypatch):
    # The trusted catalog result is server-derived. A mixed pair cannot promote a live after image.
    from agent import api

    job_id = dispatched_job(tmp_path)
    before, after, rework_after = image_bytes("red"), image_bytes("green"), image_bytes("blue")
    monkeypatch.setattr(api, "known_synthetic_fixture", lambda raw, _normalized: raw == before)
    with client_for(tmp_path) as client:
        select_crew(client)
        assert client.post(f"/api/jobs/{job_id}/accept", headers=crew_headers("a", 0)).status_code == 200
        assert client.post(f"/api/jobs/{job_id}/check-in", headers=crew_headers("c", 1), json={
            "latitude": 41.8, "longitude": -87.6}).status_code == 200
        first = client.post(f"/api/jobs/{job_id}/proof", headers=crew_headers("first", 2), files={
            "before": ("before.jpg", before, "image/jpeg"),
            "after": ("after.jpg", after, "image/jpeg"), "metadata": (None, "{}")})
        assert first.status_code == 202, first.text
    with Store(tmp_path / "b4.sqlite3") as store, store.transaction() as tx:
        first_job = store.get_job(job_id)
        original = store.get_submission(first_job.latest_submission_id)
        tx.replace_job(first_job.model_copy(update={"status": "REWORK_REQUIRED", "state_revision": 4}), 3)
    with client_for(tmp_path) as client:
        select_crew(client)
        # Presence matters: null is still an illegal rework before claim.
        rejected = client.post(f"/api/jobs/{job_id}/proof", headers=crew_headers("null-before", 4), files={
            "after": ("after.jpg", rework_after, "image/jpeg"),
            "metadata": (None, '{"before_observed_at":null}')})
        assert rejected.status_code == 422
        rework = client.post(f"/api/jobs/{job_id}/proof", headers=crew_headers("rework", 4), files={
            "after": ("after.jpg", rework_after, "image/jpeg"), "metadata": (None, "{}")})
        assert rework.status_code == 202, rework.text
    with Store(tmp_path / "b4.sqlite3") as store:
        newest = store.get_submission(store.get_job(job_id).latest_submission_id)
        assert newest.id != original.id and newest.before_evidence_id == original.before_evidence_id
        assert store.get_evidence(original.before_evidence_id).provenance == "synthetic"
        assert store.get_evidence(original.after_evidence_id).provenance == "live"
        assert store.get_evidence(newest.after_evidence_id).provenance == "live"


def test_crew_routes_publish_the_header_only_job_revision_contract(tmp_path):
    # Keep the public boundary from drifting back to body/metadata expected revisions.
    with client_for(tmp_path) as client:
        paths = client.get("/openapi.json").json()["paths"]
    for route in ("/api/jobs/{job_id}/accept", "/api/jobs/{job_id}/check-in", "/api/jobs/{job_id}/proof"):
        parameters = paths[route]["post"]["parameters"]
        assert {item["name"] for item in parameters if item["in"] == "header" and item["required"]} == {
            "Idempotency-Key", "X-Steward-Expected-Revision", "Origin", "X-Steward-Request"}
    assert "requestBody" not in paths["/api/jobs/{job_id}/accept"]["post"]
