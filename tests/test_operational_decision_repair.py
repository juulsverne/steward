"""Regression coverage for reviewed B10A contracts, causality and intent gates."""
import json
import sqlite3

import pytest
from test_crew import crew_headers, select_crew
from test_dispatch import create_plan, dispatch, prepare
from test_investigation import context
from test_investigation_repair import client_for, headers, photo
from test_settlement import inspected_job, real_exception, settle

from agent import operations as op
from agent.store import Store, StoreTransaction


def post_intent(client, key, revision, kind, decision_type="REQUEST_OPERATOR", **basis):
    field = "expected_job_revision" if kind in {"settlement", "completion_operator", "rework"} else "expected_issue_revision"
    return client.post("/api/issues/issue/operational-decisions", headers=headers(key, revision), json={
        "decision_type": decision_type, "summary": "Independent review proposal",
        "basis": {"kind": kind, field: revision, **basis}})


def test_openapi_documents_every_body_and_query(tmp_path):
    with client_for(tmp_path) as client:
        paths = client.get("/openapi.json").json()["paths"]
    bodies = ["/api/signals", "/api/issues", "/api/jobs/{job_id}/check-in", "/api/jobs/{job_id}/proof",
        "/api/jobs/{job_id}/inspect", "/api/issues/{issue_id}/geocode", "/api/issues/{issue_id}/sources",
        "/api/issues/{issue_id}/service-records/search", "/api/issues/{issue_id}/classification",
        "/api/issues/{issue_id}/jurisdiction", "/api/issues/{issue_id}/decisions",
        "/api/issues/{issue_id}/investigation-action", "/api/issues/{issue_id}/official-dispute"]
    missing = [path for path in bodies if "requestBody" not in paths[path]["post"]]
    for path in ("/api/signals/related", "/api/issues/similar"):
        if not any(p["in"] == "query" for p in paths[path]["get"].get("parameters", [])):
            missing.append(path + " query")
    assert not missing, missing


def test_openapi_discriminator_mapping_resolves(tmp_path):
    with client_for(tmp_path) as client:
        doc = client.get("/openapi.json").json()
    schema = doc["paths"]["/api/issues/{issue_id}/operational-decisions"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    mapping = schema["properties"]["basis"]["discriminator"]["mapping"]
    for reference in mapping.values():
        value = doc
        for part in reference[2:].split("/"):
            assert part in value, (reference, part)
            value = value[part]


def test_canonical_intake_evidence_is_valid_dispatch_intent_evidence(tmp_path):
    plan_id, revision = create_plan(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        evidence_ids = store.get_plan(plan_id).basis.evidence_ids
        assert evidence_ids
        links = store.evidence_associations(evidence_ids[0])
        assert all(link.issue_id is None for link in links)
        assert any(store.issue_for_signal(link.signal_id).id == "issue" for link in links)
    with client_for(tmp_path) as client:
        response = client.post("/api/issues/issue/operational-decisions", headers=headers("evidence-intent", revision), json={
            "decision_type": "REQUEST_DISPATCH", "summary": "Use the actual classification evidence",
            "evidence_ids": list(evidence_ids), "basis": {"kind": "dispatch", "plan_id": plan_id,
                "vendor_id": "south_loop_services", "expected_issue_revision": revision}})
    assert response.status_code == 200, response.text


def test_authority_terminal_issue_records_forbidden_gate(tmp_path):
    _, revision = prepare(tmp_path, authority="city")
    with Store(tmp_path / "b4.sqlite3") as store:
        store.db.execute("UPDATE issues SET status='INVALID' WHERE id='issue'")
        store.db.commit()
    with client_for(tmp_path) as client:
        actual = client.post("/api/issues/issue/exceptions", headers=headers("actual", revision),
            json={"kind": "authority", "reason_code": "authority_uncertain"})
        assert actual.status_code == 409, actual.text
        response = post_intent(client, "terminal-authority", revision, "authority")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["decision"]["gate_results"][0]["allowed"] is False, response.text


def test_no_vendor_stale_plan_records_forbidden_gate(tmp_path, monkeypatch):
    _, revision = create_plan(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store, store.transaction() as tx:
        issue = store.get_issue_record("issue")
        tx.replace_issue(issue.model_copy(update={"state_revision": issue.state_revision + 1}), issue.state_revision)
    original = Store.list_vendors
    monkeypatch.setattr(Store, "list_vendors", lambda self: tuple(v.model_copy(update={"available": False}) for v in original(self)))
    with client_for(tmp_path) as client:
        actual = client.post("/api/issues/issue/exceptions", headers=headers("actual", revision + 1),
            json={"kind": "no_vendor", "reason_code": "no_eligible_vendor"})
        assert actual.status_code == 422, actual.text
        response = post_intent(client, "stale-plan-vendors", revision + 1, "no_vendor")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["decision"]["gate_results"][0]["allowed"] is False, response.text


def test_dispatch_bad_allocation_is_error_not_allowed_intent(tmp_path):
    plan_id, revision = create_plan(tmp_path, budget=60000)
    with client_for(tmp_path) as client:
        actual = dispatch(client, plan_id, revision)
        assert actual.status_code == 403 and "budget_unavailable_or_inconsistent" in actual.json()["unmet"]
        response = post_intent(client, "bad-allocation", revision, "dispatch", "REQUEST_DISPATCH",
            plan_id=plan_id, vendor_id="south_loop_services")
    assert response.json()["outcome"] == "ERROR", response.text


def test_unlinked_link_rejects_inconsistent_saved_policy(tmp_path):
    prepare(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        item = photo(store, tmp_path, "bad-policy")
        invocation = next(row for row in store.pending_invocations() if row.signal_id == item.id)
        # Corrupt immutable metadata in isolated fixture only; domain must fail closed.
        row = json.loads(store.db.execute("SELECT record_json FROM invocations WHERE id=?", (invocation.id,)).fetchone()[0])
        row["policy_version"] = "wrong-policy"
        store.db.execute("UPDATE invocations SET record_json=? WHERE id=?", (json.dumps(row), invocation.id))
        store.db.commit()
        revision = store.get_issue_record("issue").state_revision
    with client_for(tmp_path) as client:
        response = client.post("/api/issues/issue/sources", headers={**headers("bad-link", revision),
            "X-Steward-Invocation-Id": invocation.id}, json={"signal_id": item.id, "match_rationale": "same case"})
    assert response.status_code >= 400, response.text


def test_rework_replay_revalidates_immutable_operator_cause(tmp_path, monkeypatch):
    _job, _proof, _exception, choice = real_exception(tmp_path, chosen=True)
    with client_for(tmp_path) as client:
        first = post_intent(client, "rework", 4, "rework", "REQUEST_REWORK", operator_decision_id=choice.record_id)
        assert first.status_code == 200, first.text
    with Store(tmp_path / "b4.sqlite3") as store:
        invocation = store.invocation_for_decision(choice.record_id)
    original = Store.get_event
    def corrupt(self, event_id):
        event = original(self, event_id)
        return (event.model_copy(update={"payload": event.payload.model_copy(update={"decision_id": "wrong-choice"})})
            if event_id == invocation.trigger_event_id else event)
    monkeypatch.setattr(Store, "get_event", corrupt)
    with client_for(tmp_path) as client:
        fresh = post_intent(client, "rework-new", 4, "rework", "REQUEST_REWORK", operator_decision_id=choice.record_id)
        assert fresh.status_code == 422, fresh.text
        replay = post_intent(client, "rework", 4, "rework", "REQUEST_REWORK", operator_decision_id=choice.record_id)
    assert replay.status_code >= 400, replay.text


def test_old_completion_operator_proposal_after_real_rework_is_saved_forbidden(tmp_path):
    job, proof, exception_id, choice = real_exception(tmp_path, chosen=True)
    with Store(tmp_path / "b4.sqlite3") as store:
        exception = store.get_exception(exception_id)
        op.request_rework(store, decision_id=choice.record_id, context=context("request_rework", "actual", 4))
    with client_for(tmp_path) as client:
        response = post_intent(client, "old-completion", 4, "completion_operator", job_id=job,
            submission_id=proof, verification_id=exception.verification_id, denial_event_id=exception.denial_event_id)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["decision"]["gate_results"][0]["allowed"] is False


def test_receipt_failure_rolls_back_intent_and_both_events(tmp_path, monkeypatch):
    plan, revision = create_plan(tmp_path)
    def counts():
        with Store(tmp_path / "b4.sqlite3") as store:
            return tuple(store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("decisions", "events", "request_receipts", "jobs", "ledger"))
    before = counts()
    def fail(*_):
        raise sqlite3.OperationalError("independent injected write failure")
    monkeypatch.setattr(StoreTransaction, "save_request", fail)
    with client_for(tmp_path) as client:
        result = client.post("/api/issues/issue/operational-decisions", headers=headers("rollback", revision), json={
            "decision_type": "REQUEST_DISPATCH", "summary": "Atomic intent",
            "basis": {"kind": "dispatch", "plan_id": plan, "vendor_id": "south_loop_services",
                "expected_issue_revision": revision}})
    assert result.status_code == 503, result.text
    assert counts() == before


def test_saved_settlement_replays_after_payment_and_paid_resolve_uses_history(tmp_path, monkeypatch):
    from agent import vision
    job, proof = inspected_job(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        verification = store.current_verification(job)
        issue_revision = store.get_issue_record("issue").state_revision
    body = {"decision_type": "REQUEST_SETTLEMENT", "summary": "Current proof qualifies",
        "basis": {"kind": "settlement", "job_id": job, "submission_id": proof,
            "verification_id": verification.id, "expected_job_revision": 4}}
    with client_for(tmp_path) as client:
        first = client.post("/api/issues/issue/operational-decisions", headers=headers("settlement-intent", 4), json=body)
        assert first.status_code == 200, first.text
        paid = settle(client, job, proof)
        assert paid.status_code == 200, paid.text
    monkeypatch.setattr(vision, "TOOL_DESCRIPTION", "later configuration, not the paid physical request")
    with client_for(tmp_path) as client:
        replay = client.post("/api/issues/issue/operational-decisions", headers=headers("settlement-intent", 4), json=body)
        assert replay.json() == first.json()
        resolved = client.post("/api/issues/issue/operational-decisions", headers=headers("resolve", issue_revision), json={
            "decision_type": "RESOLVE", "summary": "Historical paid acceptance",
            "basis": {"kind": "resolve", "job_id": job, "payment_id": paid.json()["data"]["record_id"],
                "submission_id": proof, "verification_id": verification.id, "expected_issue_revision": issue_revision}})
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["data"]["decision"]["gate_results"][0]["allowed"] is True


def test_resident_intake_cannot_supply_service_invocation_header(tmp_path):
    with client_for(tmp_path) as client:
        select_crew(client, "resident-1")
        result = client.post("/api/signals", headers={**crew_headers("human-invocation", 0),
            "X-Steward-Invocation-Id": "invented-service-invocation"}, files={
                "description": (None, "A couch blocks the sidewalk"), "location": (None, "State St & Madison St (demo)")})
    assert result.status_code == 403, result.text


def test_all_post_contracts_have_correct_media_headers_and_bodyless_operations(tmp_path):
    from jsonschema import Draft202012Validator

    with client_for(tmp_path) as client:
        document = client.get("/openapi.json").json()
    bodyless = {"accept_job", "cancel_job", "close_issue", "request_rework", "inspect_intake_photo"}
    multipart = {"submit_signal", "submit_proof"}
    no_revision = {"submit_signal", "select_demo_persona", "create_issue_from_signal", "inspect_intake_photo"}
    controls = {f"runtime_{name}" for name in ("claim", "renew", "prepare", "load", "begin", "finish",
                "reconcile", "requests", "authorize", "observe", "complete")}
    seen_controls = set()
    seen_resume = False
    for path in document["paths"].values():
        if "post" not in path:
            continue
        operation = path["post"]
        name = operation["operationId"]
        if name in controls:
            seen_controls.add(name)
            parameters = {parameter["name"] for parameter in operation.get("parameters", [])}
            assert "Idempotency-Key" not in parameters and "X-Steward-Expected-Revision" not in parameters
            body = operation["requestBody"]
            assert body["required"] and set(body["content"]) == {"application/json"}
            schema = body["content"]["application/json"]["schema"]
            assert schema["additionalProperties"] is False and "nonce" in schema["required"]
            assert {"claim", "owner", "command", "attempt_id"} <= set(schema["properties"])
            continue
        if name == "resume_invocation":
            seen_resume = True
            assert "requestBody" not in operation
            assert {parameter["name"] for parameter in operation.get("parameters", [])} == {"invocation_id"}
            continue
        assert ("requestBody" not in operation) == (name in bodyless), name
        parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
        assert parameters["Idempotency-Key"]["required"], name
        if name not in no_revision:
            assert parameters["X-Steward-Expected-Revision"]["required"], name
        if name not in bodyless:
            expected_type = "multipart/form-data" if name in multipart else "application/json"
            assert set(operation["requestBody"]["content"]) == {expected_type}, name
            assert operation["requestBody"]["required"], name
    assert seen_controls == controls and seen_resume
    path = "/api/issues/{issue_id}/operational-decisions".replace("~", "~0").replace("/", "~1")
    reference = f"#/paths/{path}/post/requestBody/content/application~1json/schema"
    validator = Draft202012Validator({**document, "$ref": reference})
    proposal = {"decision_type": "REQUEST_DISPATCH", "summary": "Use saved evidence",
        "basis": {"kind": "dispatch", "plan_id": "plan", "vendor_id": "vendor", "expected_issue_revision": 1}}
    assert validator.is_valid(proposal)
    assert not validator.is_valid({**proposal, "summary": "x" * 2001})
    assert not validator.is_valid({**proposal, "basis": {**proposal["basis"], "quote_cents": 1}})
    assert not validator.is_valid({**proposal, "basis": {**proposal["basis"], "expected_issue_revision": "1"}})


@pytest.mark.parametrize("ownership", ["unlinked", "other_issue", "foreign_district", "missing"])
def test_intent_rejects_evidence_without_this_canonical_issue(tmp_path, ownership):
    from agent import investigation as inv

    plan, revision = create_plan(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        evidence_id = "missing"
        if ownership != "missing":
            item = photo(store, tmp_path, "other-evidence")
            evidence_id = store.evidence_for_entity(signal_id=item.id)[0].id
            if ownership != "unlinked":
                created = inv.create_issue_from_signal(store, signal_id=item.id, rationale="different physical site",
                    context=context("create_issue_from_signal", "other-issue"))
                if ownership == "foreign_district":
                    # A synthetic legacy plan supplies only the foreign authorization
                    # boundary. It is never qualified for dispatch or used as proof.
                    foreign = store.get_plan(plan).model_copy(update={"id": "foreign-boundary-plan",
                        "issue_id": created.result.data.record_id, "district_id": "foreign", "basis": None})
                    with store.transaction() as tx:
                        tx.insert_plan(foreign)
        before = tuple(store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("decisions", "events", "request_receipts"))
    with client_for(tmp_path) as client:
        result = client.post("/api/issues/issue/operational-decisions", headers=headers("foreign-evidence", revision), json={
            "decision_type": "REQUEST_DISPATCH", "summary": "Unrelated evidence must not be cited",
            "evidence_ids": [evidence_id], "basis": {"kind": "dispatch", "plan_id": plan,
                "vendor_id": "south_loop_services", "expected_issue_revision": revision}})
    assert result.status_code == 404, result.text
    with Store(tmp_path / "b4.sqlite3") as store:
        after = tuple(store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("decisions", "events", "request_receipts"))
        assert before == after


def test_rework_intent_replays_after_handling_and_stale_denial_still_requires_authentic_event(tmp_path, monkeypatch):
    job, proof, exception_id, choice = real_exception(tmp_path, chosen=True)
    with Store(tmp_path / "b4.sqlite3") as store:
        exception = store.get_exception(exception_id)
    with client_for(tmp_path) as client:
        original = post_intent(client, "saved-rework", 4, "rework", "REQUEST_REWORK", operator_decision_id=choice.record_id)
        assert original.status_code == 200, original.text
        acted = client.post(f"/api/operator-decisions/{choice.record_id}/rework", headers=headers("actual-rework", 4))
        assert acted.status_code == 200, acted.text
        replay = post_intent(client, "saved-rework", 4, "rework", "REQUEST_REWORK", operator_decision_id=choice.record_id)
        assert replay.json() == original.json()
    read_event = Store.get_event
    def damaged(self, event_id):
        event = read_event(self, event_id)
        if event_id == exception.denial_event_id:
            event = event.model_copy(update={"event_type": "OTHER_EVENT"})
        return event
    monkeypatch.setattr(Store, "get_event", damaged)
    with client_for(tmp_path) as client:
        result = post_intent(client, "damaged-history", 4, "completion_operator", job_id=job,
            submission_id=proof, verification_id=exception.verification_id, denial_event_id=exception.denial_event_id)
    assert result.status_code >= 400 and result.json()["outcome"] == "ERROR", result.text


def test_financial_denial_payload_matches_published_error_schema(tmp_path):
    from jsonschema import Draft202012Validator

    job, proof = inspected_job(tmp_path, partial=True)
    with client_for(tmp_path) as client:
        denial = settle(client, job, proof)
        assert denial.status_code == 403, denial.text
        document = client.get("/openapi.json").json()
    reference = "#/paths/~1api~1jobs~1{job_id}~1settle/post/responses/403/content/application~1json/schema"
    Draft202012Validator({**document, "$ref": reference}).validate(denial.json())
