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


class MutationContext(Record):
    actor: ActorContext
    operation: Text
    idempotency_key: Text
    invocation_id: Text | None = None
    expected_revision: Nonnegative | None = None


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
    checked_in_at: Timestamp | None = None
    accepted_at: Timestamp | None = None
    submitted_at: Timestamp | None = None
    paid_at: Timestamp | None = None
    latest_submission_id: Text | None = None
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


class ExceptionRecord(Record):
    id: Text
    issue_id: Text
    job_id: Text | None = None
    submission_id: Text | None = None
    verification_id: Text | None = None
    denial_event_id: Positive | None = None
    kind: Literal["completion", "authority", "no_vendor"]
    reason_code: Text
    unmet: tuple[Text, ...]
    scope: Text
    before_evidence_id: Text | None = None
    after_evidence_id: Text | None = None
    status: Literal["PENDING", "DECIDED", "HANDLED"] = "PENDING"
    state_revision: Nonnegative = 0
    created_at: Timestamp
    handled_at: Timestamp | None = None

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
    created_at: Timestamp
    handled_at: Timestamp | None = None

    @model_validator(mode="after")
    def operator(self):
        if self.actor.actor_type != "operator":
            raise ValueError("operator decision requires operator actor")
        return self


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
    metadata: ModelRunMetadata | None = None
    created_at: Timestamp


class SignalReceipt(Record):
    signal_id: Text
    received_at: Timestamp
    issue_id: Text | None = None
    event_id: Positive
    invocation_id: Text | None = None


class EntityResult(Record):
    """Typed reference response for persistence receipts of later operations."""

    record_id: Text
    state_revision: Nonnegative | None = None


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
    result: ToolResult[SignalReceipt | EntityResult]
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
