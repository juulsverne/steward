"""Dependency-light request DTOs shared by the API and later HTTP tools."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from . import contracts as c


class OperationalDecisionProposalRequest(c.Record):
    decision_type: c.OperationalDecisionType
    summary: c.Text = Field(max_length=2000)
    evidence_ids: tuple[c.OpaqueId, ...] = Field(default=(), max_length=64)
    basis: c.OperationalDecisionProposalBasis

    @model_validator(mode="after")
    def matching_basis(self):
        expected = {
            "dispatch": "REQUEST_DISPATCH",
            "settlement": "REQUEST_SETTLEMENT",
            "completion_operator": "REQUEST_OPERATOR",
            "authority": "REQUEST_OPERATOR",
            "no_vendor": "REQUEST_OPERATOR",
            "budget": "REQUEST_OPERATOR",
            "rework": "REQUEST_REWORK",
            "resolve": "RESOLVE",
        }[self.basis.kind]
        if self.decision_type != expected:
            raise ValueError("operational decision type does not match basis")
        return self


class PersonaRequest(c.Record):
    persona_id: c.OpaqueId


class PlanRequest(c.Record):
    classification_fact_id: c.OpaqueId


class DispatchRequest(c.Record):
    vendor_id: c.OpaqueId


class CheckinRequest(c.Record):
    latitude: float
    longitude: float
    accuracy_m: float | None = None
    claimed_at: c.Timestamp | None = None


class ProofMetadata(c.Record):
    before_observed_at: c.Timestamp | None = None
    after_observed_at: c.Timestamp | None = None


class InspectCompletionRequest(c.Record):
    submission_id: c.OpaqueId


class CompletionExceptionRequest(c.Record):
    submission_id: c.OpaqueId
    verification_id: c.OpaqueId
    denial_event_id: c.Positive
    reason_code: c.Text


class IssueExceptionRequest(c.Record):
    kind: Literal["authority", "no_vendor", "budget"]
    reason_code: c.Text
    denial_event_id: c.Positive | None = None


class RequestCompletionRequest(c.Record):
    submission_id: c.OpaqueId
    expected_job_revision: c.Nonnegative


class IssueCreateRequest(c.Record):
    signal_id: c.OpaqueId
    match_rationale: c.Text


class StoredSignalRequest(c.Record):
    signal_id: c.OpaqueId


class LinkSignalRequest(StoredSignalRequest):
    match_rationale: c.Text


class ClassificationProposalRequest(c.Record):
    signal_id: c.OpaqueId
    category: c.Text
    visible_objects: tuple[c.Text, ...] = ()
    hazards: tuple[c.Text, ...] = ()
    primary_target: c.Text | None = None
    full_cleanup_scope: c.Text | None = None
    marked_work_area: c.Text | None = None
    large_object_count: c.Nonnegative | None = None
    supporting_evidence_ids: tuple[c.OpaqueId, ...] = ()
    unknowns: tuple[c.Text, ...] = ()


class JurisdictionProposalRequest(c.Record):
    classification_fact_id: c.OpaqueId
    responsibility: Literal["district", "city", "private", "unknown"]
    supporting_fact_ids: tuple[c.OpaqueId, ...] = ()
    unknowns: tuple[c.Text, ...] = ()


class DecisionProposalRequest(c.Record):
    decision_type: c.DecisionType
    summary: c.Text
    evidence_ids: tuple[c.OpaqueId, ...] = ()


class InvestigationActionRequest(c.Record):
    decision_id: c.OpaqueId


class ExceptionListView(c.Record):
    exceptions: tuple[c.ExceptionDetail, ...]


class CandidateSignalView(c.Record):
    id: c.Text
    source_role: c.Text
    source_author_id: c.Text | None
    text: c.Text
    observed_at: c.Timestamp | None
    image_evidence_ids: tuple[c.Text, ...] = ()


class CandidateSignalsView(c.Record):
    candidates: tuple[CandidateSignalView, ...]
    truncated: bool = False


class SimilarIssueView(c.Record):
    id: c.Text
    status: c.IssueStatus
    location: c.Text
    evidence_score: c.Nonnegative


class SimilarIssuesView(c.Record):
    candidates: tuple[SimilarIssueView, ...]
    truncated: bool = False


class HealthView(c.Record):
    ok: bool


class IntakeReceiptView(c.Record):
    """Safe acknowledgment: receipt identity is the saved signal identity."""

    receipt_id: c.Text
    signal_id: c.Text
    received_at: c.Timestamp
    accepted: bool = True
    processing: str = "PENDING"


class ValidationDetail(c.Record):
    code: str = "INVALID_FIELD"
    location: str


class ValidationView(c.Record):
    errors: tuple[ValidationDetail, ...]


class PersonaChoice(c.Record):
    persona_id: c.OpaqueId
    label: c.Text
    actor_type: Literal["resident", "crew", "operator"]


class DemoSessionView(c.Record):
    sandbox: Literal[True] = True
    notice: str = "Demo sandbox — seeded personas; do not submit private information."
    actor: c.ActorContext | None = None
    personas: tuple[PersonaChoice, ...]


class ReceiptView(c.Record):
    receipt_id: c.Text
    signal_id: c.Text
    received_at: c.Timestamp
    accepted: Literal[True] = True
    processing: Literal["PENDING"] = "PENDING"


class IssueView(c.Record):
    id: c.Text
    category: c.Text
    location: c.Text
    status: c.IssueStatus
    state_revision: c.Nonnegative
    evidence_score: c.Nonnegative
    components: c.EvidenceComponents
    responsibility: c.Text | None
    hazards: tuple[c.Text, ...]


class CrewJobView(c.Record):
    id: c.Text
    issue_id: c.Text
    vendor_id: c.Text
    status: c.JobStatus
    state_revision: c.Nonnegative
    location: c.Text
    scope: c.Text
    work_area: c.Text
    price_cents: c.Positive
    proof_requirements: c.ProofRequirements
    accepted_at: c.Timestamp | None
    checkin_claimed_at: c.Timestamp | None = None
    checked_in_at: c.Timestamp | None
    submitted_at: c.Timestamp | None
    latest_submission_id: c.Text | None
    rework_instructions: c.Text | None
    simulated: Literal[True] = True
    plan_id: c.Text
    primary_target: c.Text | None = None
    dispatch_location: c.LocationRecord | None = None
    required_equipment: tuple[c.Text, ...] = ()
    crew_count: c.Positive
    reservation_id: c.Text | None = None
    policy_version: c.Text


class EvidenceView(c.Record):
    id: c.Text
    content_type: Literal["image/jpeg", "image/png"]
    provenance: c.Provenance
    observed_at: c.Timestamp | None
    received_at: c.Timestamp


class VendorOptions(c.Record):
    plan: c.PlanRecord
    issue_revision: c.Nonnegative
    vendors: tuple[c.VendorRecord, ...]
