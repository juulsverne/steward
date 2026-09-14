"""Persisted service contracts. These are not public mutation/authorization inputs.

Store transactions own persistence; later operation services must recompute policy under
the same lock before writing. Money, accepted findings and actor context never come from
untrusted HTTP bodies. SQLite details stay in store/migrations. The lead owns changes to
these shared contracts; B2/B10 publish narrower HTTP models and their OpenAPI schemas.

Relational contract (schema 2): a signal has at most one issue link; its receipt actor
is independent of its witness/source author. Immutable evidence can acquire append-only
signal/issue/job associations. Jobs reference a plan of the same issue and one vendor;
one active job per issue and one job per plan. Submissions/inspections/exceptions and
operator decisions retain exact same-job/issue/proof relationships. One reservation and
one payment per job; one payment per reservation; ledger terminal consumption/release
is mutually exclusive. One operator choice per exception; one open completion exception
per job. One invocation per trigger; request keys are unique by actor/operation/key and
changed payloads conflict. IDs and integer money/state columns are relational authority;
nested findings are typed, never generic model-supplied authority blobs.

V1 uses one named Store bound to one trusted server-configured district policy. IssueRecord
does not introduce multi-tenant district ownership. B2 must bind/check the configured
actor district before reads and check saved plan/vendor scope once those records exist.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from .models import utc_time
from .verification import VisionFindings

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Nonnegative = Annotated[int, Field(ge=0)]
Positive = Annotated[int, Field(gt=0)]
Timestamp = Annotated[datetime, AfterValidator(utc_time)]
Provenance = Literal["seeded", "live", "synthetic"]
ActorType = Literal["resident", "crew", "operator", "service"]
Outcome = Literal["OK", "DENIED", "NEEDS_REVIEW", "NOT_FOUND", "ERROR"]
IssueStatus = Literal[
    "CANDIDATE", "MONITORING", "ACTIONABLE", "RESOLUTION_ACTIVE", "RESOLVED",
    "DISPUTED", "ROUTED_EXTERNAL", "DUPLICATE", "INVALID", "ESCALATED",
]
JobStatus = Literal[
    "POSTED", "ASSIGNED", "CHECKED_IN", "PROOF_SUBMITTED", "VERIFIED", "PAID",
    "REWORK_REQUIRED", "REJECTED", "CANCELLED",
]
DecisionType = Literal[
    "MONITOR", "MARK_ACTIONABLE", "DISPUTE_OFFICIAL_STATUS", "ROUTE_EXTERNAL",
    "REQUEST_DISPATCH", "REQUEST_SETTLEMENT", "REQUEST_OPERATOR", "REQUEST_REWORK", "RESOLVE",
]
OperationalDecisionType = Literal[
    "REQUEST_DISPATCH", "REQUEST_SETTLEMENT", "REQUEST_OPERATOR", "REQUEST_REWORK", "RESOLVE",
]
TriggerType = Literal["SIGNAL_RECEIVED", "PROOF_SUBMITTED", "OPERATOR_DECISION"]
InvocationStatus = Literal["PENDING", "RUNNING", "WAITING", "COMPLETED", "ERROR"]


class Record(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, allow_inf_nan=False)


class ActorContext(Record):
    actor_id: Text
    actor_type: ActorType
    label: Text
    vendor_id: Text | None = None
    district_id: Text | None = None

    @model_validator(mode="after")
    def crew_vendor(self):
        if self.actor_type == "crew" and self.vendor_id is None:
            raise ValueError("crew actor requires vendor_id")
        return self


class LocationRecord(Record):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    accuracy_m: Annotated[float, Field(ge=0)] | None = None
    provenance: Provenance


class EvidenceComponents(Record):
    image: Nonnegative = 0
    independent_sources: Nonnegative = 0
    precise_geocode: Nonnegative = 0
    service_match: Nonnegative = 0
    persistence: Nonnegative = 0


class VerificationComponents(Record):
    gps_within_30m: Nonnegative
    after_later_than_before: Nonnegative
    target_removed: Nonnegative
    no_new_hazard: Nonnegative
    area_clear: Nonnegative


class GateRecord(Record):
    name: Text
    allowed: bool
    unmet: tuple[Text, ...] = ()


class DispatchProposalBasis(Record):
    kind: Literal["dispatch"] = "dispatch"
    plan_id: Text
    vendor_id: Text
    expected_issue_revision: Nonnegative


class SettlementProposalBasis(Record):
    kind: Literal["settlement"] = "settlement"
    job_id: Text
    submission_id: Text
    verification_id: Text
    expected_job_revision: Nonnegative


class CompletionOperatorProposalBasis(Record):
    kind: Literal["completion_operator"] = "completion_operator"
    job_id: Text
    submission_id: Text
    verification_id: Text
    denial_event_id: Positive
    expected_job_revision: Nonnegative


class AuthorityOperatorProposalBasis(Record):
    kind: Literal["authority"] = "authority"
    expected_issue_revision: Nonnegative


class NoVendorOperatorProposalBasis(Record):
    kind: Literal["no_vendor"] = "no_vendor"
    expected_issue_revision: Nonnegative


class BudgetOperatorProposalBasis(Record):
    kind: Literal["budget"] = "budget"
    denial_event_id: Positive
    expected_issue_revision: Nonnegative


class ReworkProposalBasis(Record):
    kind: Literal["rework"] = "rework"
    operator_decision_id: Text
    expected_job_revision: Nonnegative


class ResolveProposalBasis(Record):
    kind: Literal["resolve"] = "resolve"
    job_id: Text
    payment_id: Text
    submission_id: Text
    verification_id: Text
    expected_issue_revision: Nonnegative


OperationalDecisionProposalBasis = Annotated[
    DispatchProposalBasis | SettlementProposalBasis | CompletionOperatorProposalBasis
    | AuthorityOperatorProposalBasis | NoVendorOperatorProposalBasis | BudgetOperatorProposalBasis
    | ReworkProposalBasis | ResolveProposalBasis,
    Field(discriminator="kind"),
]


class OperationalDecisionBasis(Record):
    """Server-resolved immutable snapshot for an operational proposal."""

    proposal: OperationalDecisionProposalBasis
    actual_issue_revision: Nonnegative
    actual_job_revision: Nonnegative | None = None
    plan_id: Text | None = None
    vendor_id: Text | None = None
    job_id: Text | None = None
    submission_id: Text | None = None
    verification_id: Text | None = None
    exception_id: Text | None = None
    operator_decision_id: Text | None = None
    payment_id: Text | None = None
    denial_event_id: Positive | None = None


class ModelUsage(Record):
    inputTokens: Nonnegative | None = None
    outputTokens: Nonnegative | None = None
    totalTokens: Nonnegative | None = None
    cacheReadInputTokens: Nonnegative | None = None
    cacheWriteInputTokens: Nonnegative | None = None


class ModelMetrics(Record):
    latencyMs: Nonnegative | None = None


class ModelRunMetadata(Record):
    role: Literal["text", "image"]
    model_id: Text
    text_model_id: Text | None = None
    vision_model_id: Text | None = None
    region: Text
    prompt_version: Text
    request_id: Text | None = None
    usage: ModelUsage | None = None
    metrics: ModelMetrics | None = None
    attempt_count: Positive | None = None
    trace_ref: Text | None = None
    stop_reason: Text | None = None
    wall_time_ms: Nonnegative | None = None


class RuntimeAuthority(Record):
    """Private transport assertion, excluded from every immutable domain fingerprint."""
    attempt_id: Text
    owner: Text
    fence: Positive
    command_json: Text


class MutationContext(Record):
    actor: ActorContext
    operation: Text
    idempotency_key: Text
    invocation_id: Text | None = None
    expected_revision: Nonnegative | None = None
    runtime: RuntimeAuthority | None = None


class IssueRecord(Record):
    id: Text
    category: Text
    location: Text
    status: IssueStatus
    state_revision: Nonnegative
    evidence_score: Annotated[int, Field(ge=0, le=100)]
    components: EvidenceComponents
    created_at: Timestamp
    resolved_at: Timestamp | None = None
    accepted_submission_id: Text | None = None
    responsibility: Text | None = None
    hazards: tuple[Text, ...] = ()
    signal_ids: tuple[Text, ...] = ()


class ProofRequirements(Record):
    check_in: bool = True
    before_image: bool = True
    fresh_after_image: bool = True
    same_scene: bool = True
    target_removed: bool = True
    no_new_hazard: bool = True
    area_clear: bool = True


class PlanFactReference(Record):
    id: Text
    fact_version: Positive
    source_issue_revision: Nonnegative


class PlanInspectionReference(Record):
    """Requesting association and original successful inference are distinct records."""

    inspection_id: Text
    source_inspection_id: Text
    claim_id: Text
    signal_id: Text
    evidence_id: Text
    evidence_sha256: Digest
    cache_key: Digest


class PlanBasis(Record):
    classification: PlanFactReference
    jurisdiction: PlanFactReference
    geocode: PlanFactReference
    issue_revision_before_plan: Nonnegative
    issue_revision_after_plan: Positive
    evidence_ids: tuple[Text, ...]
    inspections: tuple[PlanInspectionReference, ...]
    provenance: Provenance

    @model_validator(mode="after")
    def revision_transition(self):
        if self.issue_revision_after_plan != self.issue_revision_before_plan + 1:
            raise ValueError("plan basis requires exactly one issue revision transition")
        return self


class PlanRecord(Record):
    id: Text
    issue_id: Text
    district_id: Text
    service_type: Text
    condition: Text
    scope: Text
    work_area: Text
    required_equipment: tuple[Text, ...]
    crew_count: Positive
    large_objects: Nonnegative = 0
    quote_cents: Positive
    proof_requirements: ProofRequirements = Field(default_factory=ProofRequirements)
    policy_version: Text
    state_revision: Nonnegative = 0
    created_at: Timestamp
    # Absent only on legacy B1 rows. B5 never qualifies a legacy plan for dispatch.
    primary_target: Text | None = None
    dispatch_location: LocationRecord | None = None
    basis: PlanBasis | None = None


class VendorRecord(Record):
    id: Text
    name: Text
    insurance_verified: bool
    service_categories: tuple[Text, ...]
    service_area: tuple[Text, ...]
    equipment: tuple[Text, ...]
    available: bool
    distance_km: Annotated[float, Field(ge=0)]
    workload: Nonnegative
    performance: Annotated[float, Field(ge=0)]
    provenance: Provenance
    seed_version: Text


class JobRecord(Record):
    id: Text
    issue_id: Text
    plan_id: Text
    vendor_id: Text
    price_cents: Positive
    status: JobStatus = "POSTED"
    state_revision: Nonnegative = 0
    created_at: Timestamp
    checkin_location: LocationRecord | None = None
    checkin_claimed_at: Timestamp | None = None
    checked_in_at: Timestamp | None = None
    accepted_at: Timestamp | None = None
    submitted_at: Timestamp | None = None
    paid_at: Timestamp | None = None
    latest_submission_id: Text | None = None
    # The B7 inspector owns assigning this pointer; a newer crew proof clears it.
    current_verification_id: Text | None = None
    rework_instructions: Text | None = None
    simulated: Literal[True] = True


class EvidenceRecord(Record):
    """Immutable bytes identity; ownership is appended in EvidenceAssociation records."""

    id: Text
    image_ref: OpaqueId
    image_sha256: Digest
    content_type: Literal["image/jpeg", "image/png"]
    size_bytes: Positive
    provenance: Provenance
    received_at: Timestamp
    observed_at: Timestamp | None = None
    perceptual_hash: Annotated[str, Field(pattern=r"^[0-9a-f]+$")] | None = None
    object_version: Text | None = None
    location: LocationRecord | None = None

    @model_validator(mode="after")
    def observation_order(self):
        if self.observed_at is not None and self.observed_at > self.received_at:
            raise ValueError("observation cannot be later than receipt")
        return self


class EvidenceAssociation(Record):
    id: Text
    evidence_id: Text
    role: Literal["signal", "before", "completion"]
    signal_id: Text | None = None
    issue_id: Text | None = None
    job_id: Text | None = None
    created_at: Timestamp

    @model_validator(mode="after")
    def owner(self):
        if self.signal_id is None and self.issue_id is None:
            raise ValueError("evidence association requires signal or issue")
        if self.job_id is not None and self.issue_id is None:
            raise ValueError("job evidence requires issue")
        return self


class SignalEvidenceBundle(Record):
    """Typed optional insert owned by the same intake transaction as its signal receipt."""

    evidence: EvidenceRecord
    association: EvidenceAssociation

    @model_validator(mode="after")
    def signal_owner(self):
        if self.association.role != "signal" or self.association.signal_id is None:
            raise ValueError("signal evidence bundle requires a signal association")
        if self.association.evidence_id != self.evidence.id:
            raise ValueError("signal evidence association must match evidence")
        return self


class SubmissionRecord(Record):
    id: Text
    issue_id: Text
    job_id: Text
    before_evidence_id: Text
    after_evidence_id: Text
    submitted_by: ActorContext
    submitted_at: Timestamp
    job_revision: Nonnegative

    @model_validator(mode="after")
    def crew(self):
        if self.submitted_by.actor_type != "crew":
            raise ValueError("proof submission requires crew actor")
        if self.before_evidence_id == self.after_evidence_id:
            raise ValueError("before and after require distinct evidence IDs")
        return self


class VerificationRecord(Record):
    id: Text
    issue_id: Text
    job_id: Text
    submission_id: Text
    findings: VisionFindings
    components: VerificationComponents
    prerequisites: tuple[GateRecord, ...]
    unmet: tuple[Text, ...] = ()
    policy_version: Text
    metadata: ModelRunMetadata
    inspected_at: Timestamp
    job_revision: Nonnegative
    # `job_revision` is the inspected input revision. The result may legitimately
    # advance a later reinspection without rewriting the immutable submission.
    result_job_revision: Nonnegative | None = None
    basis: CompletionInspectionBasis | None = None
    checks: CompletionInspectionChecks | None = None
    attempt_id: Text | None = None


class CompletionInspectionBasis(Record):
    """Frozen bytes, plan scope, and physical request configuration for one inspection."""

    cache_key: Digest
    submission_id: Text
    plan_id: Text
    before_evidence_id: Text
    after_evidence_id: Text
    before_sha256: Digest
    after_sha256: Digest
    primary_target: Text
    scope: Text
    work_area: Text
    dispatch_location: LocationRecord
    model_id: Text
    region: Text
    profile: Text | None = None
    prompt_version: Text
    schema_version: Text
    request_version: Text
    preprocessing_version: Text
    configuration_version: Text
    policy_version: Text
    # Legacy rows remain readable, but cannot authorize a new physical request.
    request_json: Text | None = None


class CompletionInspectionChecks(Record):
    gps_within_30m: bool | None
    after_later_than_before: bool | None
    reuse_detected: bool | None
    distance_m: Annotated[float, Field(ge=0)] | None = None
    checkin_location: LocationRecord | None = None
    dispatch_location: LocationRecord | None = None
    before_observed_at: Timestamp | None = None
    after_observed_at: Timestamp | None = None
    cutoff_event_id: Positive | None = None
    prior_completions: tuple[CompletionReference, ...] = ()
    unmet: tuple[Text, ...] = ()


class CompletionReference(Record):
    submission_id: Text
    job_id: Text
    after_evidence_id: Text
    image_sha256: Digest
    perceptual_hash: Text | None = None
    dhash_distance: Nonnegative | None = None


class CompletionInspectionAttempt(Record):
    """Durable bounded physical-attempt record. ERROR never fabricates a verification."""

    id: Text
    actor: ActorContext
    operation: Text
    idempotency_key: Text
    request_sha256: Digest
    job_id: Text
    issue_id: Text
    submission_id: Text
    cache_key: Digest
    basis: CompletionInspectionBasis
    expected_revision: Nonnegative | None = None
    invocation_id: Text | None = None
    physical_call_count: Nonnegative | None = None
    status: Literal["RUNNING", "FINISHED", "ABANDONED"] = "RUNNING"
    outcome: Literal["SUCCESS", "ERROR"] | None = None
    error_code: Text | None = None
    metadata: ModelRunMetadata | None = None
    findings: VisionFindings | None = None
    cached_from_id: Text | None = None
    cache_eligible: bool = False
    started_at: Timestamp
    expires_at: Timestamp
    finished_at: Timestamp | None = None

    @model_validator(mode="after")
    def outcome_integrity(self):
        if self.status == "RUNNING" and self.outcome is not None:
            raise ValueError("running attempt cannot have outcome")
        if self.outcome == "SUCCESS" and self.findings is None:
            raise ValueError("successful inspection requires findings")
        if self.outcome == "ERROR" and (self.findings is not None or self.error_code is None):
            raise ValueError("failed inspection requires a bounded error")
        return self


class CompletionInspectionObservation(Record):
    """Immutable physical outcome, retained even after a claim loses authority."""

    id: Text
    attempt_id: Text
    metadata: ModelRunMetadata | None = None
    findings: VisionFindings | None = None
    error_code: Text | None = None
    observed_at: Timestamp


class ExceptionRecord(Record):
    id: Text
    issue_id: Text
    job_id: Text | None = None
    submission_id: Text | None = None
    verification_id: Text | None = None
    denial_event_id: Positive | None = None
    kind: Literal["completion", "authority", "no_vendor", "budget"]
    reason_code: Text
    unmet: tuple[Text, ...]
    scope: Text
    before_evidence_id: Text | None = None
    after_evidence_id: Text | None = None
    status: Literal["PENDING", "DECIDED", "HANDLED", "CANCELLED"] = "PENDING"
    state_revision: Nonnegative = 0
    created_at: Timestamp
    handled_at: Timestamp | None = None
    cancelled_at: Timestamp | None = None
    cancellation_event_id: Positive | None = None

    @model_validator(mode="after")
    def completion_proof(self):
        if self.kind == "completion" and any(value is None for value in (
            self.job_id, self.submission_id, self.verification_id, self.denial_event_id,
            self.before_evidence_id, self.after_evidence_id,
        )):
            raise ValueError("completion exception requires exact proof, verification and denial")
        if self.submission_id is not None and self.job_id is None:
            raise ValueError("submission requires job")
        return self


class OperatorDecisionRecord(Record):
    id: Text
    exception_id: Text
    issue_id: Text
    job_id: Text
    submission_id: Text
    actor: ActorContext
    choice: Literal["REQUEST_COMPLETION"] = "REQUEST_COMPLETION"
    reason: Text
    expected_exception_revision: Nonnegative
    expected_job_revision: Nonnegative | None = None
    created_at: Timestamp
    handled_at: Timestamp | None = None

    @model_validator(mode="after")
    def operator(self):
        if self.actor.actor_type != "operator":
            raise ValueError("operator decision requires operator actor")
        return self


class ExceptionDetail(Record):
    """Operator/service-safe saved explanation; private byte locations stay server-only."""

    id: Text
    issue_id: Text
    job_id: Text | None = None
    submission_id: Text | None = None
    verification_id: Text | None = None
    kind: Literal["completion", "authority", "no_vendor", "budget"]
    reason_code: Text
    status: Literal["PENDING", "DECIDED", "HANDLED", "CANCELLED"]
    state_revision: Nonnegative
    job_revision: Nonnegative | None = None
    scope: Text
    primary_target: Text | None = None
    work_area: Text | None = None
    before_evidence_id: Text | None = None
    after_evidence_id: Text | None = None
    denial_event_id: Positive | None = None
    components: VerificationComponents | None = None
    total: Nonnegative | None = None
    findings: VisionFindings | None = None
    checks: CompletionInspectionChecks | None = None
    prerequisites: tuple[GateRecord, ...] = ()
    score_gate: GateRecord | None = None
    payment_threshold: Literal[95] = 95
    unmet: tuple[Text, ...] = ()
    allowed_next: tuple[Text, ...] = ()
    decision_id: Text | None = None
    invocation_id: Text | None = None
    invocation_status: InvocationStatus | None = None
    handled_at: Timestamp | None = None
    cancelled_at: Timestamp | None = None
    cancellation_event_id: Positive | None = None


class BudgetRecord(Record):
    id: Text
    initial_cents: Nonnegative
    policy_version: Text
    state_revision: Nonnegative = 0


class ReservationRecord(Record):
    id: Text
    budget_id: Text
    issue_id: Text
    job_id: Text
    amount_cents: Positive
    status: Literal["RESERVED", "CONSUMED", "RELEASED"] = "RESERVED"
    state_revision: Nonnegative = 0
    created_at: Timestamp
    closed_at: Timestamp | None = None


class PaymentRecord(Record):
    id: Text
    issue_id: Text
    job_id: Text
    reservation_id: Text
    submission_id: Text
    verification_id: Text
    amount_cents: Positive
    status: Literal["SIMULATED_SETTLED"] = "SIMULATED_SETTLED"
    idempotency_key: Text
    created_at: Timestamp
    simulated: Literal[True] = True


class LedgerEntry(Record):
    id: Text
    budget_id: Text
    job_id: Text
    reservation_id: Text
    payment_id: Text | None = None
    kind: Literal["RESERVE", "CONSUME", "RELEASE"]
    amount_cents: Positive
    event_id: Positive
    created_at: Timestamp

    @model_validator(mode="after")
    def payment_link(self):
        if (self.kind == "CONSUME") != (self.payment_id is not None):
            raise ValueError("only consumption requires payment_id")
        return self


class BudgetAvailability(Record):
    budget_id: Text
    initial_cents: Nonnegative
    reserved_cents: Nonnegative
    spent_cents: Nonnegative
    available_cents: Nonnegative


class DispatchAuditFacts(Record):
    plan_id: Text
    vendor_id: Text
    expected_issue_revision: Nonnegative
    actual_issue_revision: Nonnegative
    computed_quote_cents: Positive | None = None
    budget: BudgetAvailability | None = None
    reservation_id: Text | None = None
    unresolved_hazards: tuple[Text, ...] = ()
    hazard_sources: tuple[HazardSource, ...] = ()


class SettlementAuditFacts(Record):
    action: Literal["settle", "cancel", "close"]
    plan_id: Text
    reservation_id: Text | None = None
    payment_id: Text | None = None
    submission_id: Text | None = None
    verification_id: Text | None = None
    expected_job_revision: Nonnegative | None = None
    actual_job_revision: Nonnegative
    expected_issue_revision: Nonnegative | None = None
    actual_issue_revision: Nonnegative
    original_amount_cents: Positive
    budget: BudgetAvailability | None = None
    action_gate: GateRecord


class EventFacts(Record):
    """Typed audit facts. No public free-form write-any-record payload."""

    summary: Text | None = None
    outcome: Outcome | None = None
    reason_code: Text | None = None
    unmet: tuple[Text, ...] = ()
    evidence_ids: tuple[Text, ...] = ()
    submission_id: Text | None = None
    exception_id: Text | None = None
    decision_id: Text | None = None
    record_id: Text | None = None
    score_components: EvidenceComponents | VerificationComponents | None = None
    gate_results: tuple[GateRecord, ...] = ()
    provenance: Provenance | None = None
    simulated: bool | None = None
    metadata: ModelRunMetadata | None = None
    dispatch: DispatchAuditFacts | None = None
    settlement: SettlementAuditFacts | None = None


class NewEvent(Record):
    issue_id: Text | None = None
    signal_id: Text | None = None
    job_id: Text | None = None
    invocation_id: Text | None = None
    event_type: Text
    timestamp: Timestamp
    actor: ActorContext
    state_revision: Nonnegative | None = None
    policy_version: Text
    payload: EventFacts

    @model_validator(mode="after")
    def entity(self):
        if self.issue_id is None and self.signal_id is None:
            raise ValueError("event requires issue or signal")
        if self.job_id is not None and self.issue_id is None:
            raise ValueError("job event requires issue")
        return self


class EventRecord(NewEvent):
    id: Positive


class DecisionRecord(Record):
    id: Text
    issue_id: Text
    job_id: Text | None = None
    trigger_event_id: Positive
    invocation_id: Text | None = None
    decision_type: DecisionType
    summary: Text
    evidence_ids: tuple[Text, ...] = ()
    score_components: EvidenceComponents | VerificationComponents
    policy_version: Text
    gate_results: tuple[GateRecord, ...] = ()
    next_actor: ActorType | None = None
    next_event: Text | None = None
    basis: OperationalDecisionBasis | None = None
    metadata: ModelRunMetadata | None = None
    created_at: Timestamp

    @model_validator(mode="after")
    def operational_basis_matches_type(self):
        if self.basis is None:
            return self
        expected = {
            "dispatch": "REQUEST_DISPATCH",
            "settlement": "REQUEST_SETTLEMENT",
            "completion_operator": "REQUEST_OPERATOR",
            "authority": "REQUEST_OPERATOR",
            "no_vendor": "REQUEST_OPERATOR",
            "budget": "REQUEST_OPERATOR",
            "rework": "REQUEST_REWORK",
            "resolve": "RESOLVE",
        }[self.basis.proposal.kind]
        if self.decision_type != expected:
            raise ValueError("operational decision basis does not match decision type")
        if self.job_id != self.basis.job_id:
            raise ValueError("operational decision job reference does not match basis")
        return self


class SignalReceipt(Record):
    signal_id: Text
    received_at: Timestamp
    issue_id: Text | None = None
    event_id: Positive
    invocation_id: Text | None = None


class SeedReceipt(Record):
    id: Text
    seed_version: Text
    policy_version: Text
    fixture_manifest_sha256: Digest
    baseline_signal_id: Text
    staged_signal_id: Text
    created_at: Timestamp
    scenario: Text = "baseline"


class EntityResult(Record):
    """Typed reference response for persistence receipts of later operations."""

    record_id: Text
    state_revision: Nonnegative | None = None


class PendingEntityResult(EntityResult):
    """New receipt shape for a durable trigger without rewriting old entity receipts."""

    invocation_id: Text


class CompletionInspectionResult(EntityResult):
    """Safe HTTP evidence snapshot; ERROR has an attempt but no invented verification."""

    kind: Literal["completion_inspection"] = "completion_inspection"
    attempt_id: Text
    job_id: Text
    submission_id: Text
    verification_id: Text | None
    input_job_revision: Nonnegative | None
    findings: VisionFindings | None = None
    checks: CompletionInspectionChecks | None = None
    prerequisites: tuple[GateRecord, ...] = ()
    components: VerificationComponents | None = None
    total: Nonnegative | None = None
    unmet: tuple[Text, ...] = ()
    metadata: ModelRunMetadata | None = None
    cached_from_id: Text | None = None
    physical_call_count: Nonnegative | None = None


class OperationalDecisionResult(EntityResult):
    """New receipt shape: save a proposal without claiming its action happened."""

    kind: Literal["operational_decision"] = "operational_decision"
    decision: DecisionRecord


ResultData = TypeVar("ResultData", bound=Record)


class ToolResult(Record, Generic[ResultData]):
    outcome: Outcome
    reason_code: Text | None = None
    data: ResultData | None = None
    unmet: tuple[Text, ...] = ()
    allowed_next: tuple[Text, ...] = ()
    evidence_ids: tuple[Text, ...] = ()
    event_ids: tuple[Positive, ...] = ()


class RequestReceipt(Record):
    id: Text
    operation: Text
    actor_id: Text
    idempotency_key: Text
    request_sha256: Digest
    signal_id: Text | None = None
    issue_id: Text | None = None
    job_id: Text | None = None
    result: ToolResult[SignalReceipt | CompletionInspectionResult | OperationalDecisionResult | PendingEntityResult | EntityResult]
    invocation_id: Text | None = None
    created_at: Timestamp


class PendingInvocationSpec(Record):
    id: Text
    trigger_type: TriggerType
    policy_version: Text


class InvocationRecord(Record):
    id: Text
    trigger_event_id: Positive
    trigger_type: TriggerType
    signal_id: Text | None = None
    issue_id: Text | None = None
    job_id: Text | None = None
    status: InvocationStatus = "PENDING"
    state_revision: Nonnegative = 0
    policy_version: Text
    created_at: Timestamp
    started_at: Timestamp | None = None
    finished_at: Timestamp | None = None
    attempt_count: Nonnegative = 0
    lease_owner: Text | None = None
    lease_expires_at: Timestamp | None = None
    fencing_token: Nonnegative = 0
    error_code: Text | None = None
    metadata: ModelRunMetadata | None = None


class SignalTrigger(Record):
    kind: Literal["SIGNAL_RECEIVED"] = "SIGNAL_RECEIVED"
    signal_id: Text


class ProofTrigger(Record):
    kind: Literal["PROOF_SUBMITTED"] = "PROOF_SUBMITTED"
    job_id: Text
    submission_id: Text


class OperatorTrigger(Record):
    kind: Literal["OPERATOR_DECISION"] = "OPERATOR_DECISION"
    job_id: Text
    submission_id: Text
    decision_id: Text
    exception_id: Text


class InvocationContext(Record):
    invocation_id: Text
    trigger_event_id: Positive
    trigger_type: TriggerType
    issue_id: Text | None = None
    job_id: Text | None = None
    policy_version: Text
    state_revision: Nonnegative
    facts: Annotated[SignalTrigger | ProofTrigger | OperatorTrigger, Field(discriminator="kind")]

    @model_validator(mode="after")
    def matching_trigger(self):
        if self.trigger_type != self.facts.kind:
            raise ValueError("context trigger type mismatch")
        if isinstance(self.facts, (ProofTrigger, OperatorTrigger)) and (
            self.job_id != self.facts.job_id or self.issue_id is None
        ):
            raise ValueError("context job/issue mismatch")
        return self


class ServiceLookupRecord(Record):
    id: Text
    issue_id: Text
    signal_id: Text
    outcome: Literal["MATCH", "NO_MATCH", "UNAVAILABLE"]
    external_record_id: Text | None = None
    status: Literal["OPEN", "IN_PROGRESS", "COMPLETED"] | None = None
    completed_at: Timestamp | None = None
    looked_up_at: Timestamp
    provenance: Provenance
    source_mode: Text = "seeded_adapter"
    error_code: Text | None = None

    @model_validator(mode="after")
    def matching_record(self):
        if self.outcome == "MATCH" and (self.external_record_id is None or self.status is None):
            raise ValueError("matched lookup requires record ID/status")
        if self.outcome != "MATCH" and any(
            x is not None for x in (self.external_record_id, self.status, self.completed_at)
        ):
            raise ValueError("unmatched lookup cannot claim a record")
        if (self.status == "COMPLETED") != (self.completed_at is not None):
            raise ValueError("COMPLETED lookup requires completion time")
        return self


class GeocodeFact(Record):
    """Immutable trusted location lookup. An unresolved address has no coordinates."""

    id: Text
    issue_id: Text
    signal_id: Text
    outcome: Literal["MATCH", "NO_MATCH", "UNAVAILABLE"]
    location: LocationRecord | None = None
    source_mode: Text
    looked_up_at: Timestamp
    provenance: Provenance
    source_issue_revision: Nonnegative
    fact_version: Positive = 1
    error_code: Text | None = None
    created_at: Timestamp

    @model_validator(mode="after")
    def location_matches_outcome(self):
        if (self.outcome == "MATCH") != (self.location is not None):
            raise ValueError("matched geocode requires coordinates and other outcomes cannot claim them")
        return self


class ClassificationFact(Record):
    """Evidence-grounded interpretation, never a policy or pricing authority."""

    id: Text
    issue_id: Text
    signal_id: Text
    category: Text
    visible_objects: tuple[Text, ...] = ()
    hazards: tuple[Text, ...] = ()
    primary_target: Text | None = None
    full_cleanup_scope: Text | None = None
    marked_work_area: Text | None = None
    large_object_count: Nonnegative | None = None
    supporting_evidence_ids: tuple[Text, ...] = ()
    unknowns: tuple[Text, ...] = ()
    source_issue_revision: Nonnegative
    fact_version: Positive = 1
    provenance: Provenance
    proposed_by: ActorContext
    metadata: ModelRunMetadata | None = None
    created_at: Timestamp


class JurisdictionFact(Record):
    """Trusted routing interpretation; this is the sole B4 responsibility fact."""

    id: Text
    issue_id: Text
    classification_fact_id: Text
    responsibility: Literal["district", "city", "private", "unknown"]
    supporting_fact_ids: tuple[Text, ...] = ()
    unknowns: tuple[Text, ...] = ()
    source_issue_revision: Nonnegative
    fact_version: Positive = 1
    provenance: Provenance
    proposed_by: ActorContext
    metadata: ModelRunMetadata | None = None
    created_at: Timestamp


class IntakePhotoFindings(Record):
    """Visible intake observations only; separate from completion verification findings."""

    visible_objects: tuple[Text, ...] = ()
    visible_hazards: tuple[Text, ...] = ()
    location_clues: tuple[Text, ...] = ()
    unknowns: tuple[Text, ...] = ()
    observations: tuple[Text, ...] = ()


class IntakeInspectionRecord(Record):
    id: Text
    signal_id: Text
    evidence_id: Text
    evidence_sha256: Digest
    cache_key: Digest
    outcome: Literal["SUCCESS", "ERROR"]
    preprocessing_version: Text
    schema_version: Text
    prompt_version: Text
    request_version: Text
    configuration_version: Text
    metadata: ModelRunMetadata | None = None
    findings: IntakePhotoFindings | None = None
    error_code: Text | None = None
    created_at: Timestamp
    cached_from_id: Text | None = None
    claim_id: Text | None = None
    cache_eligible: bool = False
    profile: Text | None = None
    model_id: Text | None = None
    region: Text | None = None

    @model_validator(mode="after")
    def complete_outcome(self):
        if self.outcome == "SUCCESS" and (self.findings is None or self.error_code is not None):
            raise ValueError("successful intake inspection requires findings and no error")
        if self.outcome == "ERROR" and (self.findings is not None or self.error_code is None):
            raise ValueError("failed intake inspection requires a bounded error and no findings")
        return self


class IntakeInspectionBasis(Record):
    cache_key: Digest
    model_id: Text
    region: Text
    profile: Text | None = None
    preprocessing_version: Text
    schema_version: Text
    prompt_version: Text
    request_version: Text
    configuration_version: Text


class IntakeInspectionClaim(Record):
    id: Text
    actor: ActorContext
    operation: Text
    idempotency_key: Text
    request_sha256: Digest
    signal_id: Text
    evidence_id: Text
    evidence_sha256: Digest
    cache_key: Digest
    basis: IntakeInspectionBasis
    status: Literal["RUNNING", "FINISHED", "ABANDONED"] = "RUNNING"
    started_at: Timestamp
    expires_at: Timestamp
    finished_at: Timestamp | None = None
    invocation_id: Text | None = None


class HazardSource(Record):
    hazard: Text
    classification_fact_id: Text | None = None
    intake_inspection_id: Text | None = None


class CurrentIssueFacts(Record):
    """Current immutable B4 facts B5 must re-read under its dispatch transaction."""

    issue_id: Text
    issue_revision: Nonnegative
    classification: ClassificationFact | None = None
    jurisdiction: JurisdictionFact | None = None
    geocode: GeocodeFact | None = None
    intake_inspections: tuple[IntakeInspectionRecord, ...] = ()
    unresolved_hazards: tuple[Text, ...] = ()
    hazard_sources: tuple[HazardSource, ...] = ()
