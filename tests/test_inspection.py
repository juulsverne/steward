"""B7 inspection tests begin with real B5 dispatch and B6 proof persistence."""
from io import BytesIO

from PIL import Image
from test_crew import crew_headers, dispatched_job, select_crew
from test_investigation_repair import client_for, headers

from agent.store import Store


def picture(color):
    output = BytesIO()
    Image.new("RGB", (24, 24), color).save(output, format="JPEG")
    return output.getvalue()


def valid_findings(*_):
    return {"findings": {"target_present_before": True, "same_scene": True,
        "target_removed": True, "no_new_hazard": True, "area_clear": True,
        "observations": ["Target and bags are absent in the after image."]},
        "request_id": "fake-request", "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        "metrics": {"latencyMs": 1}, "stop_reason": "tool_use"}


def proof_ready_job(path):
    job_id = dispatched_job(path)
    with client_for(path) as client:
        select_crew(client)
        assert client.post(f"/api/jobs/{job_id}/accept", headers=crew_headers("accept", 0)).status_code == 200
        assert client.post(f"/api/jobs/{job_id}/check-in", headers=crew_headers("check", 1), json={
            "latitude": 41.86, "longitude": -87.63, "accuracy_m": 5}).status_code == 200
        proof = client.post(f"/api/jobs/{job_id}/proof", headers=crew_headers("proof", 2), files={
            "before": ("before.jpg", picture("red"), "image/jpeg"),
            "after": ("after.jpg", picture("green"), "image/jpeg"),
            "metadata": (None, (
                '{"before_observed_at":"2026-09-12T00:00:00+00:00",'
                '"after_observed_at":"2026-09-13T00:00:00+00:00"}'))})
        assert proof.status_code == 202, proof.text
    with Store(path / "b4.sqlite3") as store:
        return job_id, store.get_job(job_id).latest_submission_id


def test_inspection_installs_current_verification_and_exact_replays(tmp_path):
    job_id, submission_id = proof_ready_job(tmp_path)
    with client_for(tmp_path, completion_inspector=valid_findings) as client:
        response = client.post(f"/api/jobs/{job_id}/inspect", headers=headers("inspect", 3),
            json={"submission_id": submission_id})
        assert response.status_code == 200, response.text
        assert client.post(f"/api/jobs/{job_id}/inspect", headers=headers("inspect", 3),
            json={"submission_id": submission_id}).json() == response.json()
    with Store(tmp_path / "b4.sqlite3") as store:
        job = store.get_job(job_id)
        verification = store.current_verification(job_id)
        assert job.status == "VERIFIED" and job.state_revision == 4
        assert verification.submission_id == submission_id
        assert verification.job_revision == 3 and verification.result_job_revision == 4
        assert verification.checks.gps_within_30m and verification.checks.after_later_than_before
        assert store.get_completion_attempt(verification.attempt_id).outcome == "SUCCESS"


def test_unknown_findings_are_real_current_result_but_not_verified(tmp_path):
    job_id, submission_id = proof_ready_job(tmp_path)
    def unknown(*_):
        result = valid_findings()
        result["findings"]["area_clear"] = None
        return result
    with client_for(tmp_path, completion_inspector=unknown) as client:
        response = client.post(f"/api/jobs/{job_id}/inspect", headers=headers("unknown", 3),
            json={"submission_id": submission_id})
        assert response.status_code == 200, response.text
    with Store(tmp_path / "b4.sqlite3") as store:
        job, verification = store.get_job(job_id), store.current_verification(job_id)
        assert job.status == "PROOF_SUBMITTED" and job.state_revision == 4
        assert "area_clear" in verification.unmet


def test_new_valid_unknown_reinspection_removes_stale_verified_state(tmp_path, monkeypatch):
    from agent import operations
    from agent.vision import VisionRequestBasis

    job_id, submission_id = proof_ready_job(tmp_path)
    with client_for(tmp_path, completion_inspector=valid_findings) as client:
        assert client.post(f"/api/jobs/{job_id}/inspect", headers=headers("pass", 3),
            json={"submission_id": submission_id}).status_code == 200
    monkeypatch.setattr(operations, "capture_request_basis", lambda: VisionRequestBasis(
        model_id="frozen-test-model-v2", region="us-west-2", profile="test"))
    def unknown(*_):
        result = valid_findings()
        result["findings"]["same_scene"] = None
        return result
    with client_for(tmp_path, completion_inspector=unknown) as client:
        response = client.post(f"/api/jobs/{job_id}/inspect", headers=headers("reinspect", 4),
            json={"submission_id": submission_id})
        assert response.status_code == 200, response.text
    with Store(tmp_path / "b4.sqlite3") as store:
        current = store.current_verification(job_id)
        assert store.get_job(job_id).status == "PROOF_SUBMITTED"
        assert current.job_revision == 4 and current.result_job_revision == 5
        assert current.basis.model_id == "frozen-test-model-v2"


def test_malformed_output_records_only_error_attempt(tmp_path):
    job_id, submission_id = proof_ready_job(tmp_path)
    with client_for(tmp_path, completion_inspector=lambda *_: {"findings": {}}) as client:
        response = client.post(f"/api/jobs/{job_id}/inspect", headers=headers("bad", 3),
            json={"submission_id": submission_id})
        assert response.status_code == 503
        data = response.json()["data"]
        assert data["verification_id"] is None and data["findings"] is None
        assert data["total"] is None and data["components"] is None
        assert data["input_job_revision"] == 3
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job_id).state_revision == 3
        assert store.db.execute("SELECT COUNT(*) FROM verifications").fetchone()[0] == 0
        assert store.db.execute("SELECT COUNT(*) FROM completion_inspection_attempts").fetchone()[0] == 1
