"""Retained B7 independent repros and repair acceptance; pre-import offline_guard required."""
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from test_inspection import picture, proof_ready_job, valid_findings
from test_investigation import ACTOR, context
from test_investigation_repair import client_for, headers
from test_vision import Client, output

from agent import contracts as c
from agent import investigation as inv
from agent import operations as op
from agent import vision
from agent.store import IdempotencyConflict, Store, StoreTransaction


def inspect(path, job, proof, *, key="review", revision=3, inspector=valid_findings, invocation=None):
    with Store(path / "b4.sqlite3") as store:
        return op.inspect_completion(store, job_id=job, submission_id=proof,
            context=context("inspect", key, revision).model_copy(update={"invocation_id": invocation}),
            image_root=path / "images", inspector=inspector)


@pytest.mark.parametrize("field,value,total,status", [
    ("area_clear", False, 90, "PROOF_SUBMITTED"),
    ("area_clear", True, 100, "VERIFIED"),
    ("target_present_before", False, 100, "PROOF_SUBMITTED"),
    ("target_present_before", None, 100, "PROOF_SUBMITTED"),
    ("same_scene", False, 100, "PROOF_SUBMITTED"),
    ("same_scene", None, 100, "PROOF_SUBMITTED"),
    ("target_removed", None, 60, "PROOF_SUBMITTED"),
])
def test_actual_findings_arithmetic_and_prerequisites(tmp_path, field, value, total, status):
    job, proof = proof_ready_job(tmp_path)
    def answer(*_):
        result = valid_findings()
        result["findings"][field] = value
        return result
    result = inspect(tmp_path, job, proof, inspector=answer)
    assert result.outcome == "OK"
    with Store(tmp_path / "b4.sqlite3") as store:
        current = store.current_verification(job)
        assert sum(current.components.model_dump().values()) == total
        assert store.get_job(job).status == status


def test_http_returns_agent_observable_inspection_details(tmp_path):
    job, proof = proof_ready_job(tmp_path)
    with client_for(tmp_path, completion_inspector=valid_findings) as client:
        result = client.post(f"/api/jobs/{job}/inspect", headers=headers("review", 3),
                             json={"submission_id": proof})
    assert result.status_code == 200
    assert "findings" in result.json()["data"], result.json()


def test_current_exact_result_new_key_does_not_advance_again(tmp_path):
    job, proof = proof_ready_job(tmp_path)
    first = inspect(tmp_path, job, proof)
    second = inspect(tmp_path, job, proof, key="same-current", revision=4,
                     inspector=lambda *_: pytest.fail("cache should avoid inference"))
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job).state_revision == 4, (first.model_dump(), second.model_dump())


class Crash(BaseException):
    pass


def test_expired_same_key_claim_can_recover_after_restart(tmp_path):
    job, proof = proof_ready_job(tmp_path)
    def crash(*_):
        raise Crash()
    with pytest.raises(Crash):
        inspect(tmp_path, job, proof, inspector=crash)
    with Store(tmp_path / "b4.sqlite3") as store:
        claim = store.completion_attempt_for_request(context("inspect", "review", 3))
        expired = claim.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
        store.db.execute("UPDATE completion_inspection_attempts SET record_json=? WHERE id=?",
                         (expired.model_dump_json(), claim.id))
        store.db.commit()
    result = inspect(tmp_path, job, proof)
    assert result.reason_code != "INSPECTION_IN_PROGRESS", result.model_dump()


def test_fenced_late_usage_is_retained(tmp_path, monkeypatch):
    job, proof = proof_ready_job(tmp_path)
    monkeypatch.setattr(op, "COMPLETION_CLAIM_SECONDS", -1)
    result = inspect(tmp_path, job, proof)
    assert result.reason_code == "INSPECTION_FENCED"
    with Store(tmp_path / "b4.sqlite3") as store:
        claim = store.completion_attempt_for_request(context("inspect", "review", 3))
        assert claim.metadata is not None, claim.model_dump()
        assert claim.metadata.usage.totalTokens == 2


def test_failed_attempt_audit_event_has_error_outcome(tmp_path):
    job, proof = proof_ready_job(tmp_path)
    result = inspect(tmp_path, job, proof, inspector=lambda *_: {"findings": {}})
    assert result.outcome == "ERROR"
    with Store(tmp_path / "b4.sqlite3") as store:
        event = store.get_event(result.event_ids[0])
        assert event.payload.outcome == "ERROR", event.model_dump()


@pytest.mark.parametrize("exception_status", ["PENDING", "DECIDED"])
def test_exception_created_during_inference_blocks_final_approval(tmp_path, exception_status):
    job, proof = proof_ready_job(tmp_path)
    def partial(*_):
        result = valid_findings()
        result["findings"]["area_clear"] = False
        return result
    first = inspect(tmp_path, job, proof, inspector=partial)
    def concurrent_exception(*_):
        with Store(tmp_path / "b4.sqlite3") as other:
            submission = other.get_submission(proof)
            verification = other.get_verification(first.data.record_id)
            with other.transaction() as tx:
                denial = tx.append_event(c.NewEvent(issue_id=submission.issue_id, job_id=job,
                    event_type="SETTLEMENT_DENIED", actor=ACTOR, timestamp=datetime.now(UTC),
                    state_revision=4, policy_version="south-loop-v3",
                    payload=c.EventFacts(outcome="DENIED", submission_id=proof,
                        record_id=verification.id, unmet=("area_clear",))))
                tx.insert_exception(c.ExceptionRecord(id="concurrent-exception", issue_id=submission.issue_id,
                    job_id=job, submission_id=proof, verification_id=verification.id, denial_event_id=denial.id,
                    kind="completion", reason_code="area_clear", unmet=("area_clear",), scope="remove bags",
                    before_evidence_id=submission.before_evidence_id, after_evidence_id=submission.after_evidence_id,
                    created_at=datetime.now(UTC), status=exception_status))
        return valid_findings()
    # A changed basis forces a real bounded fake call, where the B8 producer can race.
    with pytest.MonkeyPatch.context() as patch:
        frozen = vision.capture_request_basis()
        patch.setattr(op, "capture_request_basis", lambda: replace(frozen, model_id="new-interpretation"))
        inspect(tmp_path, job, proof, key="reinspect", revision=4, inspector=concurrent_exception)
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.open_completion_exception(job) is not None
        assert store.get_job(job).status != "VERIFIED"


def test_frozen_request_does_not_send_new_global_system_prompt(monkeypatch):
    basis = vision.capture_request_basis()
    original = vision.SYSTEM_PROMPT
    monkeypatch.setattr(vision, "SYSTEM_PROMPT", "different instructions after capture")
    client = Client(output())
    result = vision.inspect_pair_result(picture("red"), picture("green"), target="couch",
        work_area="sidewalk", client=client, basis=basis)
    assert client.calls[0]["system"][0]["text"] == original, result


@pytest.mark.parametrize("helper", ["completion", "intake"])
def test_absent_frozen_profile_does_not_use_new_environment_profile(monkeypatch, helper):
    import boto3
    selected = []
    class Session:
        def __init__(self, **kwargs):
            core = kwargs.get("botocore_session")
            selected.append(core.get_config_variable("profile") if core else
                            kwargs.get("profile_name") or os.getenv("AWS_PROFILE"))
        def client(self, *_args, **_kwargs):
            return Client(output())
    monkeypatch.setattr(boto3, "Session", Session)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
    basis = vision.capture_request_basis()
    assert basis.profile is None
    monkeypatch.setenv("AWS_PROFILE", "late-profile")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "later-default-profile")
    if helper == "completion":
        vision.build_vision_client(basis)
    else:
        inv.default_intake_inspector(b"fake", basis=c.IntakeInspectionBasis(cache_key="a" * 64,
            model_id="m", region="r", profile=None, preprocessing_version="p", schema_version="s",
            prompt_version="p", request_version="r", configuration_version="c"))
    assert selected == [None], selected
    assert os.environ["AWS_PROFILE"] == "late-profile"
    assert os.environ["AWS_DEFAULT_PROFILE"] == "later-default-profile"


def test_final_write_rollback_keeps_prior_job_and_claim(tmp_path, monkeypatch):
    job, proof = proof_ready_job(tmp_path)
    original = StoreTransaction.save_request
    def fail(self, record):
        original(self, record)
        if record.operation == "inspect":
            raise RuntimeError("injected result receipt failure")
    with monkeypatch.context() as patch:
        patch.setattr(StoreTransaction, "save_request", fail)
        with pytest.raises(RuntimeError):
            inspect(tmp_path, job, proof)
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job).state_revision == 3
        assert store.current_verification(job) is None
        assert store.db.execute("SELECT COUNT(*) FROM verifications").fetchone()[0] == 0
        assert store.completion_attempt_for_request(context("inspect", "review", 3)).status == "RUNNING"


def test_real_b6_invocation_and_wrong_proof_before_replay(tmp_path):
    from runtime_support import permit_context
    job, proof = proof_ready_job(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        invocation = store.db.execute("SELECT id FROM invocations WHERE job_id=?", (job,)).fetchone()[0]
        bound = permit_context(store, context("inspect", "review", 3).model_copy(update={"invocation_id": invocation}),
                               "inspect_completion", job_id=job, submission_id=proof)
        original_key = bound.idempotency_key
        first = op.inspect_completion(store, job_id=job, submission_id=proof, context=bound,
                                      image_root=tmp_path / "images", inspector=valid_findings)
    assert first.outcome == "OK"
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.db.execute("SELECT COUNT(*) FROM request_receipts WHERE idempotency_key=?", (original_key,)).fetchone()[0] == 1
        item = store.get_invocation(invocation)
        # Retain the real producer trigger and deliberately corrupt its job binding.
        with store.transaction() as tx:
            tx.replace_invocation(item.model_copy(update={"job_id": None,
                "state_revision": item.state_revision + 1}), item.state_revision)
    with Store(tmp_path / "b4.sqlite3") as store:
        assert bound.idempotency_key == original_key
        with pytest.raises(ValueError, match="cause identity"):
            op.inspect_completion(store, job_id=job, submission_id=proof, context=bound,
                                  image_root=tmp_path / "images", inspector=valid_findings)
        assert store.db.execute("SELECT COUNT(*) FROM request_receipts WHERE idempotency_key=?", (original_key,)).fetchone()[0] == 1


def another_proof(path, *, checkin=None, metadata=None):
    from test_crew import crew_headers, select_crew
    from test_dispatch import create_plan, dispatch
    plan, revision = create_plan(path, "second")
    with client_for(path) as client:
        result = dispatch(client, plan, revision, key="second-dispatch")
        assert result.status_code == 201, result.text
        job = result.json()["data"]["record_id"]
        select_crew(client)
        assert client.post(f"/api/jobs/{job}/accept", headers=crew_headers("second-accept", 0)).status_code == 200
        result = client.post(f"/api/jobs/{job}/check-in", headers=crew_headers("second-check", 1),
            json=checkin if checkin is not None else {"latitude": 41.86, "longitude": -87.63, "accuracy_m": 5})
        assert result.status_code == 200, result.text
        result = client.post(f"/api/jobs/{job}/proof", headers=crew_headers("second-proof", 2), files={
            "before": ("before.jpg", picture("red"), "image/jpeg"),
            "after": ("after.jpg", picture("green"), "image/jpeg"),
            "metadata": (None, json.dumps(metadata if metadata is not None else {
                "before_observed_at": "2026-09-12T00:00:00+00:00",
                "after_observed_at": "2026-09-13T00:00:00+00:00"}))})
        assert result.status_code == 202, result.text
    with Store(path / "b4.sqlite3") as store:
        return job, store.get_job(job).latest_submission_id


def test_cross_proof_cached_findings_recompute_global_reuse(tmp_path):
    job, proof = proof_ready_job(tmp_path)
    inspect(tmp_path, job, proof)
    second_job, second_proof = another_proof(tmp_path)
    result = inspect(tmp_path, second_job, second_proof, key="cross-proof",
        inspector=lambda *_: pytest.fail("same physical image basis should reuse findings"))
    assert result.outcome == "OK"
    with Store(tmp_path / "b4.sqlite3") as store:
        verification = store.current_verification(second_job)
        assert sum(verification.components.model_dump().values()) == 100
        assert verification.checks.reuse_detected is True
        assert verification.checks.prior_completions[0].submission_id == proof
        assert store.get_job(second_job).status == "PROOF_SUBMITTED"
        attempt = store.get_completion_attempt(verification.attempt_id)
        assert attempt.cached_from_id
        assert attempt.physical_call_count == 0
        assert attempt.metadata.attempt_count is None and attempt.metadata.usage is None
        assert store.completion_observation(attempt.id) is None


@pytest.mark.parametrize("checkin,metadata,points,gps,time", [
    ({"latitude": 41.81, "longitude": -87.62, "accuracy_m": 5}, None, 70, False, True),
    ({"latitude": 41.86, "longitude": -87.63}, {}, 60, None, None),
    (None, {"before_observed_at": "2026-09-13T00:00:00+00:00",
            "after_observed_at": "2026-09-12T00:00:00+00:00"}, 90, True, False),
])
def test_deterministic_check_controls(tmp_path, checkin, metadata, points, gps, time):
    job, proof = another_proof(tmp_path, checkin=checkin, metadata=metadata)
    inspect(tmp_path, job, proof)
    with Store(tmp_path / "b4.sqlite3") as store:
        verification = store.current_verification(job)
        assert sum(verification.components.model_dump().values()) == points
        assert verification.checks.gps_within_30m is gps
        assert verification.checks.after_later_than_before is time
        assert store.get_job(job).status == "PROOF_SUBMITTED"


def test_partial_result_names_failed_scope_requirement(tmp_path):
    job, proof = proof_ready_job(tmp_path)
    def partial(*_):
        answer = valid_findings()
        answer["findings"]["area_clear"] = False
        return answer
    inspect(tmp_path, job, proof, inspector=partial)
    with Store(tmp_path / "b4.sqlite3") as store:
        verification = store.current_verification(job)
        assert "area_clear" in verification.unmet, verification.model_dump()


def test_stale_revision_cannot_install_result(tmp_path):
    job, proof = proof_ready_job(tmp_path)
    def mutate(*_):
        with Store(tmp_path / "b4.sqlite3") as store:
            current = store.get_job(job)
            with store.transaction() as tx:
                tx.replace_job(current.model_copy(update={"state_revision": 4}), 3)
        return valid_findings()
    result = inspect(tmp_path, job, proof, inspector=mutate)
    assert result.reason_code == "STALE_PROOF"
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.current_verification(job) is None
        assert store.get_job(job).state_revision == 4


def test_missing_stored_image_does_not_invoke(tmp_path):
    from agent.images import ImageStorage
    job, proof = proof_ready_job(tmp_path)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ImageStorage, "open", lambda *_: (_ for _ in ()).throw(FileNotFoundError()))
        result = inspect(tmp_path, job, proof, inspector=lambda *_: pytest.fail("missing bytes must not invoke"))
    assert result.outcome == "ERROR"
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.current_verification(job) is None


def expire_request(path, key="review"):
    with Store(path / "b4.sqlite3") as store:
        claim = store.completion_attempt_for_request(context("inspect", key, 3))
        expired = claim.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
        store.db.execute("UPDATE completion_inspection_attempts SET record_json=? WHERE id=?",
                         (expired.model_dump_json(), claim.id))
        store.db.commit()
        return claim.id


def test_expired_request_has_exact_terminal_replay_and_new_key_recovers(tmp_path):
    job, proof = proof_ready_job(tmp_path)
    with pytest.raises(Crash):
        inspect(tmp_path, job, proof, inspector=lambda *_: (_ for _ in ()).throw(Crash()))
    claim_id = expire_request(tmp_path)
    expired = inspect(tmp_path, job, proof, inspector=lambda *_: pytest.fail("same-key expiry must not call"))
    assert expired.reason_code == "INSPECTION_INTERRUPTED"
    assert expired.data.attempt_id == claim_id and expired.data.verification_id is None
    recovered = inspect(tmp_path, job, proof, key="replacement")
    assert recovered.outcome == "OK"
    assert inspect(tmp_path, job, proof).model_dump_json() == expired.model_dump_json()
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job).state_revision == 4
        assert store.get_completion_attempt(claim_id).status == "ABANDONED"
        assert store.get_completion_attempt(claim_id).expected_revision == 3
        assert store.db.execute("SELECT COUNT(*) FROM verifications").fetchone()[0] == 1
        event = store.get_event(expired.event_ids[0])
        assert event.payload.outcome == "ERROR" and event.payload.reason_code == expired.reason_code
        assert event.payload.submission_id == proof


def test_different_key_takeover_fences_late_owner_without_rewriting_receipt(tmp_path):
    job, proof = proof_ready_job(tmp_path)
    snapshots = {}
    def delayed_answer(*_):
        snapshots["claim"] = expire_request(tmp_path)
        snapshots["replacement"] = inspect(tmp_path, job, proof, key="replacement")
        with Store(tmp_path / "b4.sqlite3") as store:
            snapshots["receipt"] = store.request_for_operation(context("inspect", "review", 3)).model_dump_json()
        answer = valid_findings()
        answer["request_id"] = "late-observed-request"
        answer["usage"] = {"inputTokens": 8, "outputTokens": 3, "totalTokens": 11}
        return answer
    late = inspect(tmp_path, job, proof, inspector=delayed_answer)
    assert late.reason_code == "INSPECTION_INTERRUPTED"
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.request_for_operation(context("inspect", "review", 3)).model_dump_json() == snapshots["receipt"]
        observation = store.completion_observation(snapshots["claim"])
        assert observation.metadata.usage.totalTokens == 11
        assert observation.metadata.request_id == "late-observed-request"
        assert observation.findings.area_clear is True
        old = store.get_completion_attempt(snapshots["claim"])
        assert old.status == "ABANDONED" and not old.cache_eligible and old.metadata is None
        assert store.get_job(job).state_revision == 4
        assert store.current_verification(job).id == snapshots["replacement"].data.verification_id
        assert store.db.execute("SELECT COUNT(*) FROM verifications").fetchone()[0] == 1
        with pytest.raises(IdempotencyConflict), store.transaction() as tx:
            tx.insert_completion_observation(observation.model_copy(update={"error_code": "changed"}))
    assert inspect(tmp_path, job, proof).model_dump_json() == late.model_dump_json()


def test_current_result_new_key_preserves_original_event_receipt_and_schema(tmp_path):
    job, proof = proof_ready_job(tmp_path)
    with client_for(tmp_path, completion_inspector=valid_findings) as client:
        first = client.post(f"/api/jobs/{job}/inspect", headers=headers("first", 3), json={"submission_id": proof})
        second = client.post(f"/api/jobs/{job}/inspect", headers=headers("second", 4), json={"submission_id": proof})
        assert first.json() == second.json()
        parsed = c.ToolResult[c.CompletionInspectionResult].model_validate_json(first.text)
        assert parsed.data.total == 100 and parsed.data.input_job_revision == 3
        assert parsed.data.state_revision == 4 and parsed.data.findings.same_scene is True
        assert parsed.data.checks.reuse_detected is False
        assert all(gate.allowed for gate in parsed.data.prerequisites)
        schema = client.get("/openapi.json").json()
        ref = schema["paths"]["/api/jobs/{job_id}/inspect"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        result_schema = schema["components"]["schemas"][ref.rsplit("/", 1)[1]]
        assert "CompletionInspectionResult" in str(result_schema)
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.db.execute("SELECT COUNT(*) FROM completion_inspection_attempts").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM events WHERE event_type='COMPLETION_INSPECTED'").fetchone()[0] == 1
        for row in store.db.execute("SELECT id FROM request_receipts WHERE operation='inspect'"):
            assert isinstance(store.get_request(row[0]).result.data, c.CompletionInspectionResult)


@pytest.mark.parametrize("finding,value", [("area_clear", False), ("no_new_hazard", None), ("target_removed", False)])
def test_http_unmet_and_gates_distinguish_prerequisites_from_score(tmp_path, finding, value):
    job, proof = proof_ready_job(tmp_path)
    def answer(*_):
        result = valid_findings()
        result["findings"][finding] = value
        return result
    with client_for(tmp_path, completion_inspector=answer) as client:
        response = client.post(f"/api/jobs/{job}/inspect", headers=headers("partial", 3), json={"submission_id": proof})
    result = c.ToolResult[c.CompletionInspectionResult].model_validate_json(response.text)
    assert finding in result.unmet and finding in result.data.unmet
    gates = {gate.name: gate for gate in result.data.prerequisites}
    assert gates["completion_prerequisites"].allowed is (value is not None)
    assert not gates["verification_score_min_95"].allowed


def test_frozen_physical_template_scope_and_cache_identity(monkeypatch):
    frozen = vision.capture_request_basis()
    original = json.loads(frozen.request_json)
    monkeypatch.setattr(vision, "SYSTEM_PROMPT", "new system")
    monkeypatch.setattr(vision, "DESCRIPTION_TEMPLATE", "new template {target} {scope} {work_area}")
    monkeypatch.setattr(vision, "INFERENCE_CONFIG", {"maxTokens": 99, "temperature": 0.5})
    monkeypatch.setattr(vision, "TOOL_DESCRIPTION", "new description")
    monkeypatch.setattr(vision.VisionFindings, "model_json_schema", lambda: {"type": "object", "new": True})
    client = Client(output())
    vision.inspect_pair_result(picture("red"), picture("green"), target="immutable couch",
        scope="immutable couch and three bags", work_area="marked rectangle", client=client, basis=frozen)
    sent = client.calls[0]
    assert sent["system"] == original["system"]
    assert sent["toolConfig"] == original["toolConfig"]
    assert sent["inferenceConfig"] == original["inferenceConfig"]
    assert sent["messages"][0]["content"][4]["text"] == original["messages"][0]["content"][4]["text"].format(
        target="immutable couch", scope="immutable couch and three bags", work_area="marked rectangle")
    assert vision.capture_request_basis().request_version != frozen.request_version


def test_complete_request_edit_invalidates_completion_cache(tmp_path, monkeypatch):
    job, proof = proof_ready_job(tmp_path)
    first = inspect(tmp_path, job, proof)
    calls = []
    monkeypatch.setattr(vision, "TOOL_DESCRIPTION", "Another exact observable findings instruction.")
    def fresh(*args):
        calls.append(args[2])
        return valid_findings()
    second = inspect(tmp_path, job, proof, key="new-template", revision=4, inspector=fresh)
    assert len(calls) == 1 and second.data.state_revision == 5
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_verification(first.data.record_id).basis.cache_key != calls[0].cache_key


def test_schema_four_upgrade_preserves_receipts_and_failure_rolls_back(tmp_path, monkeypatch):
    import sqlite3

    from runtime_support import remove_runtime_tables_for_legacy_fixture

    from agent import migrations
    proof_ready_job(tmp_path)
    path = tmp_path / "b4.sqlite3"
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT id,record_json FROM request_receipts ORDER BY id").fetchall()
        remove_runtime_tables_for_legacy_fixture(db)
        db.execute("DROP TABLE completion_inspection_observations")
        db.execute("DROP TABLE completion_inspection_attempts")
        db.execute("PRAGMA user_version=4")
    real = migrations._upgrade_five
    def failed(db):
        real(db)
        raise RuntimeError("injected completion migration failure")
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "_upgrade_five", failed)
        with pytest.raises(RuntimeError, match="injected"):
            Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT name FROM sqlite_master WHERE name='completion_inspection_observations'").fetchone() is None
        assert db.execute("SELECT id,record_json FROM request_receipts ORDER BY id").fetchall() == before
    with Store(path) as store:
        after = [tuple(row) for row in store.db.execute("SELECT id,record_json FROM request_receipts ORDER BY id")]
        assert after == before and store.db.execute("PRAGMA foreign_key_check").fetchall() == []
        for record_id, raw in before:
            assert json.loads(store.get_request(record_id).model_dump_json()) == json.loads(raw)


def test_concurrent_claims_call_once_and_busy_request_can_retry(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    job, proof = proof_ready_job(tmp_path)
    entered, release = Event(), Event()
    calls = []
    def slow(*_):
        calls.append(True)
        entered.set()
        assert release.wait(10)
        return valid_findings()
    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(inspect, tmp_path, job, proof, inspector=slow)
        try:
            assert entered.wait(10)
            busy = inspect(tmp_path, job, proof, key="busy", inspector=lambda *_: pytest.fail("duplicate call"))
            assert busy.reason_code == "INSPECTION_IN_PROGRESS" and not busy.event_ids
        finally:
            release.set()
        finished = pending.result(timeout=10)
    retry = inspect(tmp_path, job, proof, key="busy", revision=4, inspector=lambda *_: pytest.fail("current cache"))
    assert retry == finished and calls == [True]
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.db.execute("SELECT COUNT(*) FROM completion_inspection_attempts").fetchone()[0] == 1
