"""Safe case packets shared by server and runtime; no server or SDK imports."""
from typing import Literal

from pydantic import Field

from . import contracts as c


class SignalContext(c.Record):
    id: c.Text
    source: c.Text
    source_author_id: c.Text | None
    source_role: c.Text
    raw_text: c.Text
    reported_location: c.Text
    observed_at: c.Timestamp | None
    received_at: c.Timestamp
    provenance: c.Provenance
    repost_of: c.Text | None
    evidence_ids: tuple[c.Text, ...] = ()


class EventSummary(c.Record):
    id: c.Positive
    event_type: c.Text
    timestamp: c.Timestamp
    issue_id: c.Text | None = None
    signal_id: c.Text | None = None
    job_id: c.Text | None = None
    state_revision: c.Nonnegative | None = None
    policy_version: c.Text | None = None
    actor_type: c.Text | None = None
    summary: c.Text | None = None
    outcome: c.Outcome | None = None
    reason_code: c.Text | None = None
    record_id: c.Text | None = None
    submission_id: c.Text | None = None
    decision_id: c.Text | None = None
    exception_id: c.Text | None = None
    evidence_ids: tuple[c.Text, ...] = ()
    unmet: tuple[c.Text, ...] = ()
    gate_results: tuple[c.GateRecord, ...] = ()


class ScoreContext(c.Record):
    components: c.EvidenceComponents
    total: c.Nonnegative
    threshold: c.Positive
    actionable: bool


class EvidenceContext(c.Record):
    id: c.Text
    image_sha256: c.Digest
    provenance: c.Provenance
    received_at: c.Timestamp
    observed_at: c.Timestamp | None
    location: c.LocationRecord | None


class InspectionContext(c.Record):
    id: c.Text
    signal_id: c.Text
    evidence_id: c.Text
    outcome: Literal["SUCCESS", "ERROR"]
    findings: c.IntakePhotoFindings | None
    error_code: c.Text | None
    created_at: c.Timestamp
    cached_from_id: c.Text | None


class VerificationContext(c.Record):
    id: c.Text
    job_id: c.Text
    submission_id: c.Text
    input_job_revision: c.Nonnegative
    result_job_revision: c.Nonnegative | None
    policy_version: c.Text
    inspected_at: c.Timestamp
    findings: c.VisionFindings
    components: c.VerificationComponents
    total: c.Nonnegative
    prerequisites: tuple[c.GateRecord, ...]
    unmet: tuple[c.Text, ...]
    checks: c.CompletionInspectionChecks | None
    applicable_to_current_job_revision: bool


class PaymentContext(c.Record):
    id: c.Text
    job_id: c.Text
    reservation_id: c.Text
    submission_id: c.Text
    verification_id: c.Text
    amount_cents: c.Positive
    created_at: c.Timestamp
    simulated: Literal[True] = True


class CandidateContext(c.Record):
    kind: Literal["signal", "issue"]
    id: c.Text
    summary: c.Text
    location: c.Text
    issue_id: c.Text | None = None
    # Issue candidates carry the revision a link request must cite; signals have none.
    state_revision: c.Nonnegative | None = None


class ServiceStatusContext(c.Record):
    id: c.Text
    status: Literal["OPEN", "IN_PROGRESS", "COMPLETED"]
    provenance: c.Provenance
    completed_at: c.Timestamp | None
    conflict: Literal["none", "pending", "disputed"]


class ServiceArea(c.Record):
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float


class PolicyContext(c.Record):
    version: c.Text
    district_label: c.Text
    provenance: c.Provenance
    actionable_min_score: c.Nonnegative
    precise_geocode_max_m: c.Nonnegative
    autonomous_categories: tuple[c.Text, ...]
    route_to_city: tuple[c.Text, ...]
    never_dispatch: tuple[c.Text, ...]
    max_auto_dispatch_cents: c.Nonnegative
    auto_pay_min_score: c.Nonnegative
    service_area: ServiceArea


class ConfigurationContext(c.Record):
    prompt_version: c.Text
    tool_schema_version: c.Text
    text_model_id: c.Text
    vision_model_id: c.Text
    region: c.Text


class ReceiptSummary(c.Record):
    id: c.Text
    operation: c.Text
    outcome: c.Outcome
    event_ids: tuple[c.Positive, ...]
    record_id: c.Text | None = None
    state_revision: c.Nonnegative | None = None


class CaseContext(c.Record):
    schema_version: Literal["steward-case-v1"] = "steward-case-v1"
    invocation_id: c.Text
    invocation_revision: c.Nonnegative
    invocation_status: c.InvocationStatus
    trigger: EventSummary
    district_id: c.Text
    current_policy_version: c.Text
    policy: PolicyContext | None = None
    configuration: ConfigurationContext | None = None
    issue: c.IssueRecord | None = None
    signals: tuple[SignalContext, ...] = ()
    score: ScoreContext | None = None
    classification: c.ClassificationFact | None = None
    jurisdiction: c.JurisdictionFact | None = None
    geocode: c.GeocodeFact | None = None
    unresolved_hazards: tuple[c.Text, ...] = ()
    hazard_sources: tuple[c.HazardSource, ...] = ()
    inspections: tuple[InspectionContext, ...] = ()
    service_lookups: tuple[c.ServiceLookupRecord, ...] = ()
    applied_service_record: ServiceStatusContext | None = None
    plans: tuple[c.PlanRecord, ...] = ()
    jobs: tuple[c.JobRecord, ...] = ()
    vendors: tuple[c.VendorRecord, ...] = ()
    reservations: tuple[c.ReservationRecord, ...] = ()
    submissions: tuple[c.SubmissionRecord, ...] = ()
    proof_events: tuple[EventSummary, ...] = ()
    evidence: tuple[EvidenceContext, ...] = ()
    verifications: tuple[VerificationContext, ...] = ()
    exceptions: tuple[c.ExceptionDetail, ...] = ()
    operator_choices: tuple[c.OperatorDecisionRecord, ...] = ()
    payments: tuple[PaymentContext, ...] = ()
    budget: c.BudgetAvailability | None = None
    candidates: tuple[CandidateContext, ...] = Field(default=(), max_length=10)
    events: tuple[EventSummary, ...] = Field(default=(), max_length=20)
    next_candidates_cursor: c.Text | None = None
    next_events_cursor: c.Text | None = None
    latest_effect: EventSummary | None = None
    effect_receipts: tuple[ReceiptSummary, ...] = ()
    latest_denial: EventSummary | None = None
    latest_inspection_error: EventSummary | None = None
    saved_stop: c.Text | None = None
