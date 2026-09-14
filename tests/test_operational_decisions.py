"""B10A operational-intent contracts; all actions remain server-owned."""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError
from runtime_support import permit_context, permit_headers
from test_crew import select_crew
from test_dispatch import create_plan, dispatch, prepare
from test_investigation import ORIGIN, context
from test_investigation_repair import client_for, headers, photo
from test_settlement import inspected_job, real_exception, settle

from agent import investigation as inv
from agent.store import Store


def test_operational_proposal_accepts_only_typed_dispatch_ids_and_revision():
    from agent.api import OperationalDecisionProposalRequest

    proposal = OperationalDecisionProposalRequest.model_validate({
        "decision_type": "REQUEST_DISPATCH",
        "summary": "Dispatch the saved vendor for the saved scope.",
        "evidence_ids": (),
        "basis": {
            "kind": "dispatch",
            "plan_id": "plan-1",
            "vendor_id": "vendor-1",
            "expected_issue_revision": 4,
        },
    })
    assert proposal.basis.expected_issue_revision == 4

    with pytest.raises(ValidationError):
        OperationalDecisionProposalRequest.model_validate({
            "decision_type": "REQUEST_DISPATCH",
            "summary": "Dispatch with forged authority.",
            "basis": {
                "kind": "dispatch",
                "plan_id": "plan-1",
                "vendor_id": "vendor-1",
                "expected_issue_revision": 4,
                "quote_cents": 1,
            },
        })


def test_openapi_exposes_stable_operation_ids_and_strict_operational_schema(tmp_path):
    from agent.api import OPERATION_IDS

    with client_for(tmp_path) as client:
        client_document = client.get("/openapi.json").json()
    paths = client_document["paths"]
    published = {(method.upper(), path): entry["operationId"] for path, entries in paths.items()
                 for method, entry in entries.items()
                 if method in {"get", "post", "put", "patch", "delete"}}
    assert published == OPERATION_IDS
    assert len(set(published.values())) == len(published)
    operation = paths["/api/issues/{issue_id}/operational-decisions"]["post"]
    assert operation["operationId"] == "decide_operational"
    assert "OperationalDecisionProposalRequest" in str(operation["requestBody"])
    request_schema = str(operation["requestBody"])
    assert "quote_cents" not in request_schema and "X-Steward-Invocation-Id" in str(operation["parameters"])

    def resolve_pointer(reference):
        assert reference.startswith("#/"), reference
        value = paths_document
        for segment in reference.removeprefix("#/").split("/"):
            value = value[segment.replace("~1", "/").replace("~0", "~")]
        return value

    def check_references(value):
        if isinstance(value, dict):
            if "$ref" in value:
                resolve_pointer(value["$ref"])
            for reference in value.get("discriminator", {}).get("mapping", {}).values():
                resolve_pointer(reference)
            for item in value.values():
                check_references(item)
        elif isinstance(value, list):
            for item in value:
                check_references(item)

    paths_document = {"paths": paths, "components": client_document["components"]}
    check_references(paths_document)


def test_public_http_dtos_are_dependency_light_and_api_reexports_them():
    import agent.http_contracts as wire
    from agent.api import DispatchRequest as ApiDispatchRequest
    from agent.api import (
        OperationalDecisionProposalRequest as ApiOperationalDecisionProposalRequest,
    )

    source = Path(wire.__file__).read_text(encoding="utf-8")
    forbidden = {"api", "operations", "actors", "store"}
    imported = {
        alias.name.rsplit(".", 1)[-1]
        for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").rsplit(".", 1)[-1]
        for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)
    }
    assert not imported & forbidden
    assert ApiDispatchRequest is wire.DispatchRequest
    assert ApiOperationalDecisionProposalRequest is wire.OperationalDecisionProposalRequest


def test_operational_invocation_header_is_duplicate_safe_before_receipt_lookup(tmp_path):
    plan_id, revision = create_plan(tmp_path)
    body = {"decision_type": "REQUEST_DISPATCH", "summary": "Reject ambiguous service invocation.",
            "basis": {"kind": "dispatch", "plan_id": plan_id, "vendor_id": "south_loop_services",
                      "expected_issue_revision": revision}}
    duplicate_headers = [*headers("duplicate-invocation", revision).items(),
                         ("X-Steward-Invocation-Id", "first"),
                         ("x-steward-invocation-id", "second")]
    with client_for(tmp_path) as client:
        response = client.post("/api/issues/issue/operational-decisions", headers=duplicate_headers, json=body)
    assert response.status_code == 400
    assert response.json()["reason_code"] == "AMBIGUOUS_HEADER"
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.request_for_operation(context("decide_operational", "duplicate-invocation")) is None


def test_operational_header_and_basis_revision_mismatch_is_rejected_without_receipt(tmp_path):
    plan_id, revision = create_plan(tmp_path)
    body = {"decision_type": "REQUEST_DISPATCH", "summary": "Reject inconsistent observed revision.",
            "basis": {"kind": "dispatch", "plan_id": plan_id, "vendor_id": "south_loop_services",
                      "expected_issue_revision": revision}}
    with client_for(tmp_path) as client:
        response = client.post("/api/issues/issue/operational-decisions",
                               headers=headers("mismatched-revision", revision + 1), json=body)
    assert response.status_code == 422
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.request_for_operation(context("decide_operational", "mismatched-revision")) is None


def test_human_cannot_supply_service_invocation_header(tmp_path):
    request_headers = {"Origin": ORIGIN, "X-Steward-Request": "1", "Idempotency-Key": "human-invocation",
                       "X-Steward-Expected-Revision": "0", "X-Steward-Invocation-Id": "not-human-owned"}
    with client_for(tmp_path) as client:
        select_crew(client, "operator")
        response = client.post("/api/exceptions/not-a-record/request-completion", headers=request_headers,
                               json={"submission_id": "not-a-proof", "expected_job_revision": 0})
    assert response.status_code == 403
    assert response.json()["reason_code"] == "INVOCATION_SERVICE_ONLY"


def test_legacy_b4_receipt_shape_and_replay_remain_unchanged(tmp_path):
    _fact, revision = prepare(tmp_path)
    body = {"decision_type": "MONITOR", "summary": "Wait for a corroborating observation.", "evidence_ids": []}
    with client_for(tmp_path) as client:
        first = client.post("/api/issues/issue/decisions", headers=headers("legacy-decision", revision), json=body)
        replay = client.post("/api/issues/issue/decisions", headers=headers("legacy-decision", revision), json=body)
    assert first.status_code == 200, first.text
    assert replay.json() == first.json()
    assert set(first.json()["data"]) == {"record_id", "state_revision"}


def test_ineligible_saved_vendor_is_a_durable_dispatch_intent_not_a_dispatch(tmp_path):
    plan_id, revision = create_plan(tmp_path)
    body = {
        "decision_type": "REQUEST_DISPATCH",
        "summary": "The saved vendor lacks required equipment, so retain the proposal for review.",
        "basis": {
            "kind": "dispatch",
            "plan_id": plan_id,
            "vendor_id": "lakefront_clean_team",
            "expected_issue_revision": revision,
        },
    }
    with client_for(tmp_path) as client:
        response = client.post("/api/issues/issue/operational-decisions", headers=headers("intent", revision),
                               json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["outcome"] == "OK" and saved["reason_code"] == "DECISION_SAVED"
    assert saved["data"]["kind"] == "operational_decision"
    assert saved["data"]["decision"]["basis"]["actual_issue_revision"] == revision
    assert saved["data"]["decision"]["gate_results"][0]["allowed"] is False
    assert "vendor_missing_equipment" in saved["data"]["decision"]["gate_results"][0]["unmet"]
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_issue_record("issue").state_revision == revision
        assert store.active_job_for_issue("issue") is None


def test_operational_replay_keeps_old_truth_after_the_proposed_dispatch_happens(tmp_path):
    plan_id, revision = create_plan(tmp_path)
    body = {"decision_type": "REQUEST_DISPATCH", "summary": "Dispatch the saved eligible vendor.",
            "basis": {"kind": "dispatch", "plan_id": plan_id, "vendor_id": "south_loop_services",
                      "expected_issue_revision": revision}}
    with client_for(tmp_path) as client:
        saved = client.post("/api/issues/issue/operational-decisions", headers=headers("intent-replay", revision),
                            json=body)
        assert saved.status_code == 200, saved.text
        assert dispatch(client, plan_id, revision, key="actual-dispatch").status_code == 201
        replay = client.post("/api/issues/issue/operational-decisions", headers=headers("intent-replay", revision),
                             json=body)
    assert replay.json() == saved.json()


def test_stale_operational_dispatch_is_saved_with_observed_revision_and_failed_gate(tmp_path):
    plan_id, revision = create_plan(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store, store.transaction() as tx:
        issue = store.get_issue_record("issue")
        tx.replace_issue(issue.model_copy(update={"state_revision": issue.state_revision + 1}), issue.state_revision)
    body = {"decision_type": "REQUEST_DISPATCH", "summary": "Record the stale dispatch proposal.",
            "basis": {"kind": "dispatch", "plan_id": plan_id, "vendor_id": "south_loop_services",
                      "expected_issue_revision": revision}}
    with client_for(tmp_path) as client:
        saved = client.post("/api/issues/issue/operational-decisions", headers=headers("stale-intent", revision),
                            json=body)
    assert saved.status_code == 200, saved.text
    decision = saved.json()["data"]["decision"]
    assert decision["basis"]["actual_issue_revision"] == revision + 1
    assert "stale_issue_revision" in decision["gate_results"][0]["unmet"]


def test_real_b3_invocation_is_bound_when_it_creates_its_first_issue(tmp_path):
    with Store(tmp_path / "b4.sqlite3") as store:
        item = photo(store, tmp_path, "b3-intent")
        invocation = next(record for record in store.pending_invocations()
                          if record.signal_id == item.id)
        bound_context = permit_context(store, context("create_issue_from_signal", "b3-create").model_copy(
            update={"invocation_id": invocation.id}), "create_issue_from_signal", signal_id=item.id, match_rationale="new case")
        claimed_revision = store.get_invocation(invocation.id).state_revision
        created = inv.create_issue_from_signal(store, signal_id=item.id, rationale="new case", context=bound_context)
        issue_id = created.result.data.record_id
        bound = store.get_invocation(invocation.id)
        assert bound.issue_id == issue_id and bound.state_revision == claimed_revision + 1


def test_b3_invocation_header_survives_create_then_next_action_and_replay(tmp_path):
    with Store(tmp_path / "b4.sqlite3") as store:
        item = photo(store, tmp_path, "b3-http")
        invocation = next(record for record in store.pending_invocations()
                          if record.signal_id == item.id)
    with Store(tmp_path / "b4.sqlite3") as store:
        service_headers = permit_headers(store, context("create_issue_from_signal", "b3-create").model_copy(
            update={"invocation_id": invocation.id}), "create_issue_from_signal", signal_id=item.id,
            match_rationale="new physical observation")
    with client_for(tmp_path) as client:
        created = client.post("/api/issues", headers=service_headers,
            json={"signal_id": item.id, "match_rationale": "new physical observation"})
        assert created.status_code == 201, created.text
        issue_id = created.json()["data"]["record_id"]
        body = {"decision_type": "MONITOR", "summary": "wait for more evidence", "evidence_ids": []}
        with Store(tmp_path / "b4.sqlite3") as store:
            decision_headers = permit_headers(store, context("decide", "b3-next", created.json()["data"]["state_revision"]).model_copy(
                update={"invocation_id": invocation.id}), "record_investigation_decision", issue_id=issue_id, **body)
        first = client.post(f"/api/issues/{issue_id}/decisions", headers=decision_headers, json=body)
        replay = client.post(f"/api/issues/{issue_id}/decisions", headers=decision_headers, json=body)
    assert first.status_code == 200, first.text
    assert replay.json() == first.json()
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_invocation(invocation.id).issue_id == issue_id


def test_real_b3_invocation_is_bound_when_an_unlinked_signal_is_added_to_a_case(tmp_path):
    prepare(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        item = photo(store, tmp_path, "b3-link")
        invocation = next(record for record in store.pending_invocations()
                          if record.signal_id == item.id)
        revision = store.get_issue_record("issue").state_revision
        bound_context = permit_context(store, context("link_signal", "b3-link", revision).model_copy(
            update={"invocation_id": invocation.id}), "link_signal", issue_id="issue", signal_id=item.id,
            match_rationale="same case")
        receipt = inv.link_signal_to_issue(store, issue_id="issue", signal_id=item.id, rationale="same case", context=bound_context)
        assert receipt.result.data.record_id == "issue"
        assert store.get_invocation(invocation.id).issue_id == "issue"
        replay = inv.link_signal_to_issue(store, issue_id="issue", signal_id=item.id, rationale="same case",
            context=bound_context)
        assert replay == receipt


def test_current_completion_can_be_saved_as_settlement_intent_without_payment(tmp_path):
    job_id, submission_id = inspected_job(tmp_path)
    with Store(tmp_path / "b4.sqlite3") as store:
        verification = store.current_verification(job_id)
        assert verification is not None
    body = {
        "decision_type": "REQUEST_SETTLEMENT",
        "summary": "The current verified proof meets the saved settlement conditions.",
        "basis": {
            "kind": "settlement",
            "job_id": job_id,
            "submission_id": submission_id,
            "verification_id": verification.id,
            "expected_job_revision": 4,
        },
    }
    with client_for(tmp_path) as client:
        response = client.post("/api/issues/issue/operational-decisions", headers=headers("settle-intent", 4),
                               json=body)
    assert response.status_code == 200, response.text
    saved = response.json()["data"]["decision"]
    assert saved["job_id"] == job_id
    assert saved["basis"]["verification_id"] == verification.id
    assert saved["gate_results"] == [{"name": "settlement", "allowed": True, "unmet": []}]
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_job(job_id).status == "VERIFIED"
        assert store.payment_for_job(job_id) is None


def test_completion_operator_and_rework_intents_use_real_b8_b9_records(tmp_path):
    job_id, submission_id = inspected_job(tmp_path, partial=True)
    with client_for(tmp_path) as client:
        denial = settle(client, job_id, submission_id)
        assert denial.status_code == 403, denial.text
    with Store(tmp_path / "b4.sqlite3") as store:
        verification = store.current_verification(job_id)
        assert verification is not None
    completion_body = {
        "decision_type": "REQUEST_OPERATOR",
        "summary": "The saved completion denial needs an operator decision.",
        "basis": {"kind": "completion_operator", "job_id": job_id, "submission_id": submission_id,
                  "verification_id": verification.id, "denial_event_id": denial.json()["event_ids"][0],
                  "expected_job_revision": 4},
    }
    with client_for(tmp_path) as client:
        completion = client.post("/api/issues/issue/operational-decisions", headers=headers("operator-intent", 4),
                                 json=completion_body)
    assert completion.status_code == 200, completion.text
    assert completion.json()["data"]["decision"]["gate_results"][0]["allowed"] is True

    job_id, submission_id, _exception_id, choice = real_exception(tmp_path / "rework", chosen=True)
    rework_body = {"decision_type": "REQUEST_REWORK", "summary": "Perform the saved operator-approved rework.",
                   "basis": {"kind": "rework", "operator_decision_id": choice.record_id,
                             "expected_job_revision": 4}}
    with client_for(tmp_path / "rework") as client:
        rework = client.post("/api/issues/issue/operational-decisions", headers=headers("rework-intent", 4),
                             json=rework_body)
    assert rework.status_code == 200, rework.text
    assert rework.json()["data"]["decision"]["basis"]["operator_decision_id"] == choice.record_id


def test_pre_job_operator_intents_evaluate_actual_authority_vendor_and_budget_records(tmp_path, monkeypatch):
    _fact, authority_revision = prepare(tmp_path, authority="city")
    authority = {"decision_type": "REQUEST_OPERATOR", "summary": "Record the city-authority review.",
                 "basis": {"kind": "authority", "expected_issue_revision": authority_revision}}
    with client_for(tmp_path) as client:
        response = client.post("/api/issues/issue/operational-decisions",
                               headers=headers("authority-intent", authority_revision), json=authority)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["decision"]["gate_results"][0]["allowed"] is True

    plan_id, no_vendor_revision = create_plan(tmp_path, "no-vendor")
    original_vendors = Store.list_vendors

    def none_eligible(self):
        return tuple(record.model_copy(update={"available": False}) for record in original_vendors(self))

    monkeypatch.setattr(Store, "list_vendors", none_eligible)
    no_vendor = {"decision_type": "REQUEST_OPERATOR", "summary": "Record the lack of an eligible vendor.",
                 "basis": {"kind": "no_vendor", "expected_issue_revision": no_vendor_revision}}
    with client_for(tmp_path) as client:
        response = client.post("/api/issues/no-vendor/operational-decisions",
                               headers=headers("vendor-intent", no_vendor_revision), json=no_vendor)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["decision"]["gate_results"][0]["allowed"] is True
    assert plan_id == response.json()["data"]["decision"]["basis"]["plan_id"]

    monkeypatch.setattr(Store, "list_vendors", original_vendors)
    for index in range(6):
        prior_plan, prior_revision = create_plan(tmp_path, f"budget-prior-{index}")
        with client_for(tmp_path) as client:
            assert dispatch(client, prior_plan, prior_revision, key=f"budget-prior-{index}").status_code == 201
    plan_id, budget_revision = create_plan(tmp_path, "budget-issue")
    with client_for(tmp_path) as client:
        denial = dispatch(client, plan_id, budget_revision, key="budget-denial")
        assert denial.status_code == 403 and denial.json()["unmet"] == ["insufficient_budget"]
        budget = {"decision_type": "REQUEST_OPERATOR", "summary": "Record the authentic current budget shortage.",
                  "basis": {"kind": "budget", "denial_event_id": denial.json()["event_ids"][0],
                            "expected_issue_revision": budget_revision}}
        response = client.post("/api/issues/budget-issue/operational-decisions",
                               headers=headers("budget-intent", budget_revision), json=budget)
    assert response.status_code == 200, response.text
    saved_basis = response.json()["data"]["decision"]["basis"]
    assert saved_basis["plan_id"] == plan_id and saved_basis["vendor_id"] == "south_loop_services"
    assert response.json()["data"]["decision"]["gate_results"][0]["allowed"] is True
    with Store(tmp_path / "b4.sqlite3") as store, store.transaction() as tx:
        issue = store.get_issue_record("budget-issue")
        tx.replace_issue(issue.model_copy(update={"state_revision": issue.state_revision + 1}), issue.state_revision)
    with client_for(tmp_path) as client:
        stale = client.post("/api/issues/budget-issue/operational-decisions",
            headers=headers("stale-budget-intent", budget_revision), json=budget)
    assert stale.status_code == 200, stale.text
    stale_decision = stale.json()["data"]["decision"]
    assert stale_decision["basis"]["actual_issue_revision"] == budget_revision + 1
    assert "stale_issue_revision" in stale_decision["gate_results"][0]["unmet"]


def test_paid_chain_can_be_saved_as_resolution_intent_without_closing_issue(tmp_path):
    job_id, submission_id = inspected_job(tmp_path)
    with client_for(tmp_path) as client:
        paid = settle(client, job_id, submission_id)
        assert paid.status_code == 200, paid.text
    with Store(tmp_path / "b4.sqlite3") as store:
        payment = store.payment_for_job(job_id)
        issue = store.get_issue_record("issue")
        assert payment is not None
        verification = store.get_verification(payment.verification_id)
    body = {"decision_type": "RESOLVE", "summary": "Close the issue using the accepted paid proof.",
            "basis": {"kind": "resolve", "job_id": job_id, "payment_id": payment.id,
                      "submission_id": submission_id, "verification_id": verification.id,
                      "expected_issue_revision": issue.state_revision}}
    with client_for(tmp_path) as client:
        saved = client.post("/api/issues/issue/operational-decisions",
                            headers=headers("resolve-intent", issue.state_revision), json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["decision"]["gate_results"] == [{"name": "closure", "allowed": True, "unmet": []}]
    with Store(tmp_path / "b4.sqlite3") as store:
        assert store.get_issue_record("issue").status == "RESOLUTION_ACTIVE"
