"""Server-owned sandbox personas and reusable authorization/projection boundaries.

Public persona selection is role simulation, not verified identity. Never construct
an authoritative ActorContext from a domain request body.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from itsdangerous import BadData, URLSafeTimedSerializer
from pydantic import ValidationError

from . import contracts as c
from .store import Store

SESSION_MAX_AGE = 12 * 60 * 60
SANDBOX_NOTICE = "Demo sandbox — seeded personas; do not submit private information."


class AccessError(Exception):
    """Fixed transport reason; never supply request data or exception text here."""

    def __init__(self, status: int, reason: str, *, clear_cookie: bool = False):
        self.status = status
        self.reason = reason
        self.clear_cookie = clear_cookie
        super().__init__(reason)


class DemoPersona(c.Record):
    persona_id: c.OpaqueId
    actor: c.ActorContext


class PersonaChoice(c.Record):
    persona_id: c.OpaqueId
    label: c.Text
    actor_type: Literal["resident", "crew", "operator"]


class DemoSessionView(c.Record):
    sandbox: Literal[True] = True
    notice: str = SANDBOX_NOTICE
    actor: c.ActorContext | None = None
    personas: tuple[PersonaChoice, ...]


class SessionClaim(c.Record):
    v: Literal[1]
    persona_id: c.OpaqueId


def configured_personas() -> tuple[DemoPersona, ...]:
    """Fixed V1 catalog; stable resident identities match data/signals.json."""
    district = "south_loop_demo"
    actors = [
        DemoPersona(persona_id="resident-1", actor=c.ActorContext(
            actor_id="demo-resident-1", actor_type="resident", label="Resident 1 (seeded)",
            district_id=district)),
        DemoPersona(persona_id="resident-2", actor=c.ActorContext(
            actor_id="demo-resident-2", actor_type="resident", label="Resident 2 (seeded)",
            district_id=district)),
        DemoPersona(persona_id="operator", actor=c.ActorContext(
            actor_id="demo-operator", actor_type="operator", label="District operator (seeded)",
            district_id=district)),
    ]
    for vendor, label in (
        ("south_loop_services", "South Loop Services"),
        ("windy_city_maintenance", "Windy City Maintenance"),
        ("lakefront_clean_team", "Lakefront Clean Team"),
    ):
        actors.append(DemoPersona(persona_id=f"crew-{vendor}", actor=c.ActorContext(
            actor_id=f"demo-crew-{vendor}", actor_type="crew", label=f"{label} crew (seeded)",
            vendor_id=vendor, district_id=district)))
    return tuple(actors)


class DemoSessions:
    def __init__(self, secret: str, personas: tuple[DemoPersona, ...]):
        self._signer = URLSafeTimedSerializer(secret, salt="steward-demo-human-v1",
                                              signer_kwargs={"digest_method": hashlib.sha256})
        self._personas = {p.persona_id: p for p in personas}

    def select(self, persona_id: str) -> tuple[c.ActorContext, str]:
        persona = self._personas.get(persona_id)
        if persona is None:
            raise AccessError(403, "PERSONA_FORBIDDEN")
        return persona.actor, self._signer.dumps({"v": 1, "persona_id": persona_id})

    def resolve(self, cookie: str) -> c.ActorContext:
        try:
            if len(cookie) > 2048:
                raise ValueError("oversize session")
            claim = SessionClaim.model_validate(self._signer.loads(cookie, max_age=SESSION_MAX_AGE))
            persona = self._personas.get(claim.persona_id)
            if persona is None:
                raise ValueError("removed persona")
            return persona.actor
        except (BadData, ValidationError, ValueError, TypeError) as error:
            raise AccessError(401, "INVALID_SESSION", clear_cookie=True) from error

    def view(self, actor: c.ActorContext | None) -> DemoSessionView:
        return DemoSessionView(actor=actor, personas=tuple(
            PersonaChoice(persona_id=p.persona_id, label=p.actor.label, actor_type=p.actor.actor_type)
            for p in self._personas.values()
        ))


class Action(StrEnum):
    """Role eligibility only. These names do not register or implement operations."""

    SUBMIT_SIGNAL = "submit_signal"
    INGEST_SOURCE = "ingest_source"
    READ_RECEIPT = "read_receipt"
    READ_ISSUE = "read_issue"
    READ_JOB = "read_job"
    READ_EVIDENCE = "read_evidence"
    READ_CONTEXT = "read_context"
    INVESTIGATE = "investigate"
    APPLY_INVESTIGATION_DECISION = "apply_investigation_decision"
    ACCEPT_JOB = "accept_job"
    CHECK_IN = "check_in"
    SUBMIT_PROOF = "submit_proof"
    REQUEST_COMPLETION = "request_completion"
    DISPATCH = "dispatch"
    INSPECT = "inspect"
    SETTLE = "settle"
    CLOSE = "close"
    EDIT_POLICY = "edit_policy"


_ACTION_ROLES = {
    Action.SUBMIT_SIGNAL: {"resident", "crew", "operator"},
    Action.INGEST_SOURCE: {"service"},
    Action.READ_RECEIPT: {"resident", "crew", "operator", "service"},
    Action.READ_ISSUE: {"operator", "service"},
    Action.READ_JOB: {"crew", "operator", "service"},
    Action.READ_EVIDENCE: {"crew", "operator", "service"},
    Action.READ_CONTEXT: {"service"},
    Action.INVESTIGATE: {"service"},
    Action.APPLY_INVESTIGATION_DECISION: {"service"},
    Action.ACCEPT_JOB: {"crew"},
    Action.CHECK_IN: {"crew"},
    Action.SUBMIT_PROOF: {"crew"},
    Action.REQUEST_COMPLETION: {"operator"},
    Action.DISPATCH: {"service"},
    Action.INSPECT: {"service"},
    Action.SETTLE: {"service"},
    Action.CLOSE: {"service"},
    Action.EDIT_POLICY: set(),
}


class ReceiptView(c.Record):
    receipt_id: c.Text
    signal_id: c.Text
    received_at: c.Timestamp
    accepted: Literal[True] = True
    processing: Literal["PENDING"] = "PENDING"


class IssueView(c.Record):
    """Minimal operational summary. Full timelines belong to their later read card."""

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
    checked_in_at: c.Timestamp | None
    submitted_at: c.Timestamp | None
    latest_submission_id: c.Text | None
    rework_instructions: c.Text | None
    simulated: Literal[True] = True


class EvidenceView(c.Record):
    id: c.Text
    content_type: Literal["image/jpeg", "image/png"]
    provenance: c.Provenance
    observed_at: c.Timestamp | None
    received_at: c.Timestamp


@dataclass(frozen=True)
class AccessBoundary:
    """Trusted server actor + one configured Store district.

    Call role checks before resource reads. Mutation services must recheck resource
    ownership/current state inside their writer transaction. This is not policy approval.
    """

    actor: c.ActorContext
    district_id: str

    def require_district(self) -> None:
        if (self.actor.actor_type in {"crew", "operator", "service"}
                and self.actor.district_id != self.district_id):
            raise AccessError(403, "DISTRICT_FORBIDDEN")
        if self.actor.district_id is not None and self.actor.district_id != self.district_id:
            raise AccessError(403, "DISTRICT_FORBIDDEN")

    def require(self, action: Action) -> None:
        if self.actor.actor_type not in _ACTION_ROLES.get(action, set()):
            raise AccessError(403, "ROLE_FORBIDDEN")
        self.require_district()

    def receipt(self, store: Store, signal_id: str) -> ReceiptView:
        self.require(Action.READ_RECEIPT)
        owner = store.signal_receipt_actor(signal_id)
        if self.actor.actor_type != "service" and owner != self.actor.actor_id:
            raise AccessError(404, "RESOURCE_NOT_FOUND")
        record = store.get_signal_receipt(signal_id)
        return ReceiptView(receipt_id=record.signal_id, signal_id=record.signal_id,
                           received_at=record.received_at)

    def _issue(self, store: Store, issue_id: str) -> c.IssueRecord:
        self.require_district()
        record = store.get_issue_record(issue_id)
        if any(plan.district_id != self.district_id for plan in store.plans_for_issue(issue_id)):
            raise AccessError(404, "RESOURCE_NOT_FOUND")
        return record

    def issue(self, store: Store, issue_id: str) -> IssueView:
        self.require(Action.READ_ISSUE)
        record = self._issue(store, issue_id)
        return IssueView(id=record.id, category=record.category, location=record.location,
            status=record.status, state_revision=record.state_revision,
            evidence_score=record.evidence_score, components=record.components,
            responsibility=record.responsibility, hazards=record.hazards)

    def signal(self, store: Store, signal_id: str):
        """Service investigation scope, including signals linked after intake."""
        self.require(Action.INVESTIGATE)
        signal = store.get_signal(signal_id)
        issue = store.issue_for_signal(signal_id)
        if issue is not None:
            self._issue(store, issue.id)
        return signal

    def require_job(self, store: Store, job_id: str) -> c.JobRecord:
        """Saved ownership only; later operations also check role and policy gates."""
        self.require(Action.READ_JOB)
        job = store.get_job(job_id)
        plan = store.get_plan(job.plan_id)
        if (plan.district_id != self.district_id or plan.issue_id != job.issue_id
                or (self.actor.actor_type == "crew" and self.actor.vendor_id != job.vendor_id)):
            raise AccessError(404, "RESOURCE_NOT_FOUND")
        self._issue(store, job.issue_id)
        return job

    def job(self, store: Store, job_id: str) -> CrewJobView:
        job = self.require_job(store, job_id)
        plan = store.get_plan(job.plan_id)
        issue = self._issue(store, job.issue_id)
        return CrewJobView(id=job.id, issue_id=job.issue_id, vendor_id=job.vendor_id,
            status=job.status, state_revision=job.state_revision, location=issue.location,
            scope=plan.scope, work_area=plan.work_area, price_cents=job.price_cents,
            proof_requirements=plan.proof_requirements, accepted_at=job.accepted_at,
            checked_in_at=job.checked_in_at, submitted_at=job.submitted_at,
            latest_submission_id=job.latest_submission_id, rework_instructions=job.rework_instructions)

    def evidence(self, store: Store, evidence_id: str, *, job_id: str | None = None) -> EvidenceView:
        self.require(Action.READ_EVIDENCE)
        links = store.evidence_associations(evidence_id)
        allowed = False
        if self.actor.actor_type == "crew":
            if job_id is None:
                raise AccessError(404, "RESOURCE_NOT_FOUND")
            job = self.require_job(store, job_id)
            current = (store.get_submission(job.latest_submission_id)
                       if job.latest_submission_id is not None else None)
            for link in links:
                if link.issue_id != job.issue_id or link.job_id not in {None, job.id}:
                    continue
                if link.role == "before" or (link.role == "completion" and current is not None
                    and evidence_id in {current.before_evidence_id, current.after_evidence_id}):
                    allowed = True
        else:
            for link in links:
                if link.issue_id is not None:
                    try:
                        self._issue(store, link.issue_id)
                    except AccessError:
                        continue
                    allowed = True
                elif link.signal_id is not None and self.actor.actor_type == "service":
                    # A retained signal-only association does not prove it is still unlinked.
                    issue = store.issue_for_signal(link.signal_id)
                    if issue is not None:
                        try:
                            self._issue(store, issue.id)
                        except AccessError:
                            continue
                    allowed = True
        if not allowed:
            raise AccessError(404, "RESOURCE_NOT_FOUND")
        record = store.get_evidence(evidence_id)
        return EvidenceView(id=record.id, content_type=record.content_type,
            provenance=record.provenance, observed_at=record.observed_at, received_at=record.received_at)
