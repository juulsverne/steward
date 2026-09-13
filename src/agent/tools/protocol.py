"""Strict domain tool schemas, explicit HTTP identities and immutable commands."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import Field, create_model

from .. import contracts as c
from .. import http_contracts as h
from ..case_contracts import CaseContext
from ..http_protocol import OPERATION_IDS

SCHEMA_VERSION = "steward-http-tools-v1"
MAX_INPUT_BYTES = 128 * 1024
ENVELOPE_FIELDS = {
    "outcome",
    "reason_code",
    "data",
    "unmet",
    "allowed_next",
    "evidence_ids",
    "event_ids",
}


def bounded_json(value: Any, depth: int = 0) -> None:
    """Reject non-JSON objects/coercion and excessive structures before serialization."""
    if depth > 12:
        raise ValueError("input nesting limit")
    if value is None or type(value) in (bool, int, float):
        return
    if type(value) is str:
        if len(value) > 2000:
            raise ValueError("input text limit")
        return
    if type(value) in (list, dict):
        if len(value) > 64:
            raise ValueError("input collection limit")
        if isinstance(value, dict):
            if any(type(key) is not str for key in value):
                raise ValueError("JSON object keys must be strings")
            for key, item in value.items():
                bounded_json(key, depth + 1)
                if (
                    key.endswith("_id")
                    and isinstance(item, str)
                    and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", item)
                ):
                    raise ValueError("invalid domain identifier")
                if (
                    key.endswith("_ids")
                    and isinstance(item, list)
                    and any(
                        isinstance(identifier, str)
                        and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", identifier)
                        for identifier in item
                    )
                ):
                    raise ValueError("invalid domain identifiers")
                bounded_json(item, depth + 1)
        else:
            for item in value:
                bounded_json(item, depth + 1)
        return
    raise ValueError("input must be JSON")


def input_json(value: Any) -> str:
    bounded_json(value)
    raw = json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
    if len(raw.encode()) > MAX_INPUT_BYTES:
        raise ValueError("input byte limit")
    return raw


def _input(name, base=c.Record, **fields):
    # A before-model validator converts JSON arrays to Python lists and loses
    # strict JSON tuple semantics. Bounds are checked by input_json first.
    return create_model(name, __base__=base, **fields)


ID = (c.OpaqueId, ...)
REV = (c.Nonnegative, ...)
CompletionEscalation = _input(
    "CompletionEscalationInput",
    h.CompletionExceptionRequest,
    kind=(Literal["completion"], ...),
    job_id=ID,
    expected_job_revision=REV,
)
IssueEscalation = _input(
    "IssueEscalationInput", h.IssueExceptionRequest, issue_id=ID, expected_issue_revision=REV
)
EscalationInput = _input(
    "EscalationInput",
    basis=(Annotated[CompletionEscalation | IssueEscalation, Field(discriminator="kind")], ...),
)


@dataclass(frozen=True)
class Operation:
    name: str
    method: str
    path: str
    model: type[c.Record]
    body_model: type[c.Record] | None
    result_model: type[c.Record]
    receipt_operation: str | None
    description: str
    query: tuple[str, ...] = ()
    revision: str | None = None

    @property
    def operation_id(self) -> str:
        return OPERATION_IDS[self.method, self.path]

    @property
    def mutation(self) -> bool:
        return self.receipt_operation is not None

    @property
    def path_fields(self) -> tuple[str, ...]:
        return tuple(re.findall(r"\{(\w+)\}", self.path))

    def command(self, values: dict) -> Command:
        value = self.model.model_validate_json(input_json(values))
        values = value.model_dump(mode="json", exclude_unset=True)
        revision = values.pop(self.revision) if self.revision else None
        if self.name == "record_operational_decision":
            basis = values["basis"]
            revision = basis.get("expected_job_revision", basis.get("expected_issue_revision"))
        path = self.path.format(**values)
        query = {key: values.get(key, self.model.model_fields[key].default) for key in self.query}
        body = None
        if self.body_model:
            body = {key: values[key] for key in self.body_model.model_fields if key in values}
            self.body_model.model_validate_json(input_json(body))
        return Command(
            self.name,
            self.method,
            path,
            query=query,
            body=body,
            expected_revision=revision,
            mutation=self.mutation,
        )


def _op(
    name, method, path, body, result, receipt, description, *, revision=None, query=(), **fields
):
    model = _input(
        "".join(part.title() for part in name.split("_")) + "Input", body or c.Record, **fields
    )
    return Operation(name, method, path, model, body, result, receipt, description, query, revision)


OPERATIONS = {
    op.name: op
    for op in (
        _op(
            "find_related_signals",
            "GET",
            "/api/signals/related",
            None,
            h.CandidateSignalsView,
            None,
            "Read related observations for this signal. Compare source identity and times; related does not mean independent.",
            query=("signal_id",),
            signal_id=ID,
        ),
        _op(
            "find_similar_issues",
            "GET",
            "/api/issues/similar",
            None,
            h.SimilarIssuesView,
            None,
            "Read candidate canonical issues before choosing a match. Nearby cases need not be the same condition.",
            query=("signal_id",),
            signal_id=ID,
        ),
        _op(
            "create_issue_from_signal",
            "POST",
            "/api/issues",
            h.IssueCreateRequest,
            c.EntityResult,
            "create_issue_from_signal",
            "Create a canonical issue for the saved signal with your matching rationale.",
        ),
        _op(
            "link_signal_to_issue",
            "POST",
            "/api/issues/{issue_id}/sources",
            h.LinkSignalRequest,
            c.EntityResult,
            "link_signal",
            "Link the saved observation to a matching issue; source independence and scoring remain server rules.",
            revision="expected_issue_revision",
            issue_id=ID,
            expected_issue_revision=REV,
        ),
        _op(
            "inspect_intake_photo",
            "POST",
            "/api/signals/{signal_id}/intake-inspection",
            None,
            c.EntityResult,
            "inspect_intake_photo",
            "Inspect the saved intake photo for visible evidence. This does not classify authority or dispatch.",
            signal_id=ID,
        ),
        _op(
            "geocode_location",
            "POST",
            "/api/issues/{issue_id}/geocode",
            h.StoredSignalRequest,
            c.EntityResult,
            "record_geocode",
            "Ask the trusted adapter for location facts; unknown precision gives no invented points.",
            revision="expected_issue_revision",
            issue_id=ID,
            expected_issue_revision=REV,
        ),
        _op(
            "search_311",
            "POST",
            "/api/issues/{issue_id}/service-records/search",
            h.StoredSignalRequest,
            c.EntityResult,
            "record_service_lookup",
            "Read the seeded/live official record for this observation. COMPLETED does not prove the physical issue is resolved.",
            revision="expected_issue_revision",
            issue_id=ID,
            expected_issue_revision=REV,
        ),
        _op(
            "classify_issue",
            "POST",
            "/api/issues/{issue_id}/classification",
            h.ClassificationProposalRequest,
            c.EntityResult,
            "save_classification",
            "Propose category, visible targets, complete scope, retained hazards and supporting evidence. Do not supply scores or authority.",
            revision="expected_issue_revision",
            issue_id=ID,
            expected_issue_revision=REV,
        ),
        _op(
            "determine_jurisdiction",
            "POST",
            "/api/issues/{issue_id}/jurisdiction",
            h.JurisdictionProposalRequest,
            c.EntityResult,
            "save_jurisdiction",
            "Propose responsibility from current classification and supporting facts; policy decides authority.",
            revision="expected_issue_revision",
            issue_id=ID,
            expected_issue_revision=REV,
        ),
        _op(
            "record_investigation_decision",
            "POST",
            "/api/issues/{issue_id}/decisions",
            h.DecisionProposalRequest,
            c.EntityResult,
            "decide",
            "Record an evidence-backed investigation intention. Use the separate action tool to apply a permitted decision.",
            revision="expected_issue_revision",
            issue_id=ID,
            expected_issue_revision=REV,
        ),
        _op(
            "apply_investigation_decision",
            "POST",
            "/api/issues/{issue_id}/investigation-action",
            h.InvestigationActionRequest,
            c.EntityResult,
            "apply_investigation_decision",
            "Apply a saved investigation decision under current policy and issue revision.",
            revision="expected_issue_revision",
            issue_id=ID,
            expected_issue_revision=REV,
        ),
        _op(
            "official_dispute",
            "POST",
            "/api/issues/{issue_id}/official-dispute",
            h.InvestigationActionRequest,
            c.EntityResult,
            "official_dispute",
            "Apply a saved official-dispute decision supported by independent newer observations; this does not close the issue.",
            revision="expected_issue_revision",
            issue_id=ID,
            expected_issue_revision=REV,
        ),
        _op(
            "record_operational_decision",
            "POST",
            "/api/issues/{issue_id}/operational-decisions",
            h.OperationalDecisionProposalRequest,
            c.OperationalDecisionResult,
            "decide_operational",
            "Record dispatch, settlement, escalation, rework or resolution intention using exact saved references. Its gate preview is not an executed action or settlement denial. The basis supplies the issue/job revision.",
            issue_id=ID,
        ),
        _op(
            "build_resolution_plan",
            "POST",
            "/api/issues/{issue_id}/plan",
            h.PlanRequest,
            c.EntityResult,
            "build_resolution_plan",
            "Build a plan from current validated scope; the server derives the quote and policy checks.",
            revision="expected_issue_revision",
            issue_id=ID,
            expected_issue_revision=REV,
        ),
        _op(
            "list_eligible_vendors",
            "GET",
            "/api/plans/{plan_id}/vendors",
            None,
            h.VendorOptions,
            None,
            "Read eligible provider facts for the saved plan, then choose a provider. Do not invent availability, rates or eligibility.",
            plan_id=ID,
        ),
        _op(
            "dispatch_vendor",
            "POST",
            "/api/plans/{plan_id}/dispatch",
            h.DispatchRequest,
            c.EntityResult,
            "dispatch",
            "Request simulated dispatch to the selected eligible vendor. The API rechecks authority, quote and funds and reserves once.",
            revision="expected_issue_revision",
            plan_id=ID,
            expected_issue_revision=REV,
        ),
        _op(
            "inspect_completion",
            "POST",
            "/api/jobs/{job_id}/inspect",
            h.InspectCompletionRequest,
            c.CompletionInspectionResult,
            "inspect",
            "Inspect the exact submitted proof. Findings, checks and score are evidence, not payment; unknown and inspector failure remain distinct.",
            revision="expected_job_revision",
            job_id=ID,
            expected_job_revision=REV,
        ),
        _op(
            "release_payment",
            "POST",
            "/api/jobs/{job_id}/settle",
            h.InspectCompletionRequest,
            c.EntityResult,
            "settle",
            "Request simulated settlement for the exact proof. The API may deny incomplete work; preserve the actual denial for escalation and never blindly retry it.",
            revision="expected_job_revision",
            job_id=ID,
            expected_job_revision=REV,
        ),
        _op(
            "close_issue",
            "POST",
            "/api/issues/{issue_id}/close",
            None,
            c.EntityResult,
            "close",
            "Request closure after the saved paid contract. On recovery, existing payment means close without paying again.",
            revision="expected_issue_revision",
            issue_id=ID,
            expected_issue_revision=REV,
        ),
        _op(
            "cancel_job",
            "POST",
            "/api/jobs/{job_id}/cancel",
            None,
            c.EntityResult,
            "cancel",
            "Cancel an unpaid job under policy, releasing its original reservation once. A paid job cannot be cancelled.",
            revision="expected_job_revision",
            job_id=ID,
            expected_job_revision=REV,
        ),
        _op(
            "request_rework",
            "POST",
            "/api/operator-decisions/{decision_id}/rework",
            None,
            c.EntityResult,
            "request_rework",
            "Apply the actual saved operator Request completion choice to the same job and quote; stop awaiting fresh proof.",
            revision="expected_job_revision",
            decision_id=ID,
            expected_job_revision=REV,
        ),
        _op(
            "get_job",
            "GET",
            "/api/jobs/{job_id}",
            None,
            h.CrewJobView,
            None,
            "Read the job's current state, scope, original quote and proof requirements.",
            job_id=ID,
        ),
        _op(
            "get_exception",
            "GET",
            "/api/exceptions/{exception_id}",
            None,
            c.ExceptionDetail,
            None,
            "Read the actual exception, failed requirements and saved operator choice; do not infer a choice from conversation.",
            exception_id=ID,
        ),
        _op(
            "get_budget",
            "GET",
            "/api/budget",
            None,
            c.BudgetAvailability,
            None,
            "Read the server's current simulated allocation, reservations, spending and availability.",
        ),
    )
}

_COMPLETION = Operation(
    "escalate_completion_exception",
    "POST",
    "/api/jobs/{job_id}/exceptions",
    CompletionEscalation,
    h.CompletionExceptionRequest,
    c.EntityResult,
    "escalate_to_operator",
    "Record an exception from the actual completion denial.",
    revision="expected_job_revision",
)
_ISSUE = Operation(
    "escalate_issue_exception",
    "POST",
    "/api/issues/{issue_id}/exceptions",
    IssueEscalation,
    h.IssueExceptionRequest,
    c.EntityResult,
    "escalate_to_operator",
    "Record a supported authority, vendor or budget exception.",
    revision="expected_issue_revision",
)
OPERATIONS["escalate_to_operator"] = Operation(
    "escalate_to_operator",
    "POST",
    "",
    EscalationInput,
    None,
    c.EntityResult,
    "escalate_to_operator",
    "Escalate a completion denial with its exact proof/verification/event, or a supported pre-job authority, vendor or budget problem. This cannot invent a human decision.",
)
ROUTES = {
    **{name: op for name, op in OPERATIONS.items() if op.path},
    _COMPLETION.name: _COMPLETION,
    _ISSUE.name: _ISSUE,
    "read_case_context": _op("read_case_context", "GET", "/api/invocations/{invocation_id}/context",
        None, CaseContext, None, "Trusted host context refresh; not a model tool.",
        invocation_id=ID, candidates_cursor=(c.OpaqueId, "0"), events_cursor=(c.OpaqueId, "0"),
        query=("candidates_cursor", "events_cursor")),
}


def operation_for(name: str) -> Operation:
    if name in ROUTES:
        return ROUTES[name]
    for op in ROUTES.values():
        if op.operation_id == name:
            return op
    raise ValueError("unknown operation")


def build_command(name: str, values: dict) -> Command:
    if name == "escalate_to_operator":
        value = EscalationInput.model_validate_json(input_json(values))
        basis = value.basis.model_dump(mode="json", exclude_unset=True)
        return (_COMPLETION if basis["kind"] == "completion" else _ISSUE).command(basis)
    return operation_for(name).command(values)


@dataclass(frozen=True, init=False)
class Command:
    """Immutable wire snapshot, with tool/public/receipt identities kept distinct."""

    operation: str
    operation_id: str
    receipt_operation: str | None
    method: str
    path: str
    query_items: tuple[tuple[str, str], ...]
    body_json: str | None
    expected_revision: int | None
    mutation: bool
    schema_version: str

    def __init__(
        self, operation, method, path, query=None, body=None, expected_revision=None, mutation=None
    ):
        op = operation_for(operation)
        pattern = re.escape(op.path)
        for key in op.path_fields:
            pattern = pattern.replace(
                re.escape("{" + key + "}"), r"([A-Za-z0-9][A-Za-z0-9_.-]{0,199})"
            )
        if method != op.method or not re.fullmatch(pattern, path):
            raise ValueError("command does not match registered path")
        query = {} if query is None else query
        if set(query) != set(op.query):
            raise ValueError("command does not match registered query")
        for value in query.values():
            if type(value) is not str or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value
            ):
                raise ValueError("invalid query identifier")
        if op.body_model is None:
            if body is not None:
                raise ValueError("registered command requires absent body")
        else:
            op.body_model.model_validate_json(input_json(body))
        needs_revision = op.revision is not None or op.name == "record_operational_decision"
        if needs_revision and (type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("expected revision required")
        if not needs_revision and expected_revision is not None:
            raise ValueError("unexpected revision")
        if op.name == "record_operational_decision":
            basis = body["basis"]
            if expected_revision != basis.get(
                "expected_job_revision", basis.get("expected_issue_revision")
            ):
                raise ValueError("basis and header revisions differ")
        if mutation is not None and mutation != op.mutation:
            raise ValueError("mutation identity differs")
        for key, value in {
            "operation": op.name,
            "operation_id": op.operation_id,
            "receipt_operation": op.receipt_operation,
            "method": method,
            "path": path,
            "query_items": tuple(sorted(query.items())),
            "body_json": None if body is None else input_json(body),
            "expected_revision": expected_revision,
            "mutation": op.mutation,
            "schema_version": SCHEMA_VERSION,
        }.items():
            object.__setattr__(self, key, value)

    @property
    def body(self):
        return None if self.body_json is None else json.loads(self.body_json)

    @property
    def query(self):
        return dict(self.query_items)


def error(reason: str) -> dict:
    return c.ToolResult[c.EntityResult](outcome="ERROR", reason_code=reason).model_dump(mode="json")


def validated_envelope(payload: Any, operation: str, status: int = 200) -> dict:
    try:
        if type(payload) is not dict or set(payload) != ENVELOPE_FIELDS:
            raise ValueError("incomplete envelope")
        raw = json.dumps(payload, allow_nan=False)
        if payload["outcome"] == "OK":
            if status >= 400 or payload["data"] is None:
                raise ValueError("invalid success")
            result_type = operation_for(operation).result_model
            result = c.ToolResult[result_type].model_validate_json(raw)
            if isinstance(result.data, c.CompletionInspectionResult) and any(
                value is None
                for value in (
                    result.data.verification_id,
                    result.data.findings,
                    result.data.checks,
                    result.data.components,
                    result.data.total,
                    result.data.input_job_revision,
                    result.data.state_revision,
                )
            ):
                raise ValueError("incomplete inspection success")
        else:
            result = c.ToolResult[
                c.EntityResult | c.CompletionInspectionResult | h.ValidationView
            ].model_validate_json(raw)
        return result.model_dump(mode="json")
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        return error("MALFORMED_RESPONSE")
