"""B4 investigation operations over stored signals and trusted adapter/model facts."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from . import contracts as c
from .actors import AccessBoundary, Action
from .adapters import GeocodeResult, ServiceResult
from .config import settings
from .images import ImageStorage
from .models import ServiceRecord
from .policy import load_policy, route_category
from .scoring import dispute_supported
from .store import IdempotencyConflict, Store, request_fingerprint

POLICY_VERSION = "south-loop-v3"
INTAKE_PREPROCESSING_VERSION = "b3-normalized-jpeg-v1"
INTAKE_SCHEMA_VERSION = hashlib.sha256(
    json.dumps(c.IntakePhotoFindings.model_json_schema(), sort_keys=True).encode()
).hexdigest()[:16]
INTAKE_SYSTEM_PROMPT = (
    "Inspect this intake photo. Report only visible objects, hazards, location clues, unknowns, "
    "and concise observations through report_intake_findings. Do not infer authority, score, "
    "price, identity, dispatch, or facts outside the image."
)
INTAKE_PROMPT_VERSION = hashlib.sha256(INTAKE_SYSTEM_PROMPT.encode()).hexdigest()[:16]
INTAKE_MAX_TOKENS = 1024
INTAKE_REQUEST_TEMPLATE = {
    "system": [{"text": INTAKE_SYSTEM_PROMPT}],
    "inferenceConfig": {"maxTokens": INTAKE_MAX_TOKENS, "temperature": 0},
    "messages": [{"role": "user", "content": [{"image": {"format": "jpeg", "source": {"bytes": None}}}]}],
    "toolConfig": {"tools": [{"toolSpec": {"name": "report_intake_findings",
        "description": "Return visible-only intake findings.",
        "inputSchema": {"json": c.IntakePhotoFindings.model_json_schema()}}}],
        "toolChoice": {"tool": {"name": "report_intake_findings"}}},
}
INTAKE_REQUEST_VERSION = hashlib.sha256(json.dumps(
    INTAKE_REQUEST_TEMPLATE, sort_keys=True).encode()).hexdigest()[:16]


def stable_id(kind: str, *parts: str) -> str:
    value = ":".join(("steward", kind, *parts))
    return f"{kind}-{uuid5(NAMESPACE_URL, value)}"


def _invocation_cause(store: Store, invocation_id: str):
    """Immutable identity shared by ordinary actions and first canonical binding."""
    invocation = store.get_invocation(invocation_id)
    trigger = store.get_event(invocation.trigger_event_id)
    if (trigger.event_type != invocation.trigger_type or trigger.signal_id != invocation.signal_id
            or trigger.policy_version != invocation.policy_version or trigger.job_id != invocation.job_id):
        raise ValueError("invocation cause identity is inconsistent")
    return invocation, trigger


def _validated_cause(store: Store, context: c.MutationContext, *,
                     issue_id: str | None, signal_id: str | None, job_id: str | None = None,
                     submission_id: str | None = None) -> c.EventRecord | None:
    """Resolve the immutable intake cause through its saved canonical association.

    Invocation binding is trusted persisted state, not inferred or written here. A B3
    intake event stays issue-less even after its signal and invocation acquire a target.
    """
    if context.invocation_id is None:
        return None
    invocation, trigger = _invocation_cause(store, context.invocation_id)
    if job_id is not None and invocation.job_id is not None and invocation.job_id != job_id:
        raise ValueError("invocation cause does not belong to job")
    if job_id is not None and trigger.job_id is not None and trigger.job_id != job_id:
        raise ValueError("trigger cause does not belong to job")
    if (trigger.event_type == "PROOF_SUBMITTED" and submission_id is not None
            and trigger.payload.submission_id != submission_id):
        raise ValueError("proof invocation does not name requested submission")
    linked = store.issue_for_signal(signal_id) if signal_id is not None else None
    target_issue = issue_id if issue_id is not None else linked.id if linked is not None else None
    if invocation.issue_id != target_issue:
        raise ValueError("invocation cause does not belong to issue")
    if linked is not None and linked.id != target_issue:
        raise ValueError("requested signal contradicts invocation cause target")
    cause_issue = trigger.issue_id
    if trigger.signal_id is not None:
        canonical = store.issue_for_signal(trigger.signal_id)
        canonical_issue = canonical.id if canonical is not None else None
        if canonical_issue != target_issue:
            raise ValueError("invocation cause signal does not belong to issue")
        if trigger.issue_id is None and trigger.event_type == "SIGNAL_RECEIVED":
            cause_issue = canonical_issue
    if cause_issue != target_issue:
        raise ValueError("invocation cause does not belong to issue")
    if target_issue is None and signal_id is not None and trigger.signal_id != signal_id:
        raise ValueError("invocation cause does not belong to signal")
    return trigger


def _authorize(store, context, *, issue_id=None, signal_id=None, evidence_ids=()):
    if context is None:
        raise ValueError("investigation requires a bound service context")
    boundary = AccessBoundary(context.actor, load_policy()["district"])
    boundary.require(Action.INVESTIGATE)
    if issue_id is not None:
        boundary.issue(store, issue_id)
    if signal_id is not None:
        boundary.signal(store, signal_id)
    for evidence_id in evidence_ids:
        boundary.evidence(store, evidence_id)
    return _validated_cause(store, context, issue_id=issue_id, signal_id=signal_id)


def _authorize_unlinked_signal_transition(store, context, *, issue_id: str | None, signal_id: str):
    """Allow only an original unlinked B3 intake to acquire its first canonical issue."""
    boundary = AccessBoundary(context.actor, load_policy()["district"])
    boundary.require(Action.INVESTIGATE)
    if issue_id is not None:
        boundary.issue(store, issue_id)
    boundary.signal(store, signal_id)
    if context.invocation_id is None:
        return None
    invocation, trigger = _invocation_cause(store, context.invocation_id)
    if (invocation.trigger_type != "SIGNAL_RECEIVED" or invocation.signal_id != signal_id
            or invocation.issue_id is not None or invocation.job_id is not None
            or trigger.event_type != "SIGNAL_RECEIVED" or trigger.signal_id != signal_id
            or trigger.issue_id is not None or trigger.job_id is not None
            or store.issue_for_signal(signal_id) is not None):
        raise ValueError("invocation cannot bind this signal transition")
    return trigger


def _bind_unlinked_signal_invocation(tx, store: Store, context: c.MutationContext, *, signal_id: str,
                                     issue_id: str) -> None:
    if context.invocation_id is None:
        return
    invocation, trigger = _invocation_cause(store, context.invocation_id)
    if (invocation.trigger_type != "SIGNAL_RECEIVED" or invocation.signal_id != signal_id
            or invocation.issue_id is not None or invocation.job_id is not None
            or trigger.event_type != "SIGNAL_RECEIVED" or trigger.signal_id != signal_id
            or trigger.issue_id is not None or trigger.job_id is not None
            or store.issue_for_signal(signal_id).id != issue_id):
        raise ValueError("invocation cannot bind this signal transition")
    tx.replace_invocation(invocation.model_copy(update={"issue_id": issue_id,
        "state_revision": invocation.state_revision + 1}), invocation.state_revision)


def _expected(context):
    if context.expected_revision is None:
        raise ValueError("proposal requires expected revision")


def _provenance(origins):
    values = set(origins)
    return "synthetic" if "synthetic" in values else "seeded" if "seeded" in values else "live"


def _fact_version(store, issue_id):
    # A single monotonic per-issue domain across all B4 fact types.
    return 1 + max((row[0] for row in store.db.execute(
        "SELECT fact_version FROM classification_facts WHERE issue_id=? UNION ALL "
        "SELECT fact_version FROM jurisdiction_facts WHERE issue_id=? UNION ALL "
        "SELECT fact_version FROM geocode_facts WHERE issue_id=?", (issue_id,) * 3)), default=0)


def _action_lifecycle(store, issue):
    if issue.status not in {"CANDIDATE", "MONITORING", "ACTIONABLE", "ROUTED_EXTERNAL"}:
        raise ValueError("investigation cannot replace this lifecycle")
    if store.db.execute("SELECT id FROM jobs WHERE issue_id=? AND status NOT IN ('CANCELLED','REJECTED')",
                        (issue.id,)).fetchone():
        raise ValueError("investigation cannot replace an active job")


def _event(tx, issue_id: str, actor: c.ActorContext, event_type: str, *,
           revision: int, summary: str, record_id: str | None = None,
           score: c.EvidenceComponents | None = None, outcome: str = "OK") -> c.EventRecord:
    return tx.append_event(c.NewEvent(issue_id=issue_id, event_type=event_type,
        invocation_id=tx.runtime_context.invocation_id if tx.runtime_context else None,
        timestamp=datetime.now(UTC), actor=actor, state_revision=revision,
        policy_version=POLICY_VERSION, payload=c.EventFacts(summary=summary, record_id=record_id,
            outcome=outcome, score_components=score)))


def _receipt(*, context: c.MutationContext, fingerprint: str, issue_id: str | None,
             record_id: str, state_revision: int | None, event_ids: tuple[int, ...]) -> c.RequestReceipt:
    return c.RequestReceipt(id=str(uuid4()), operation=context.operation,
        invocation_id=context.invocation_id,
        actor_id=context.actor.actor_id, idempotency_key=context.idempotency_key,
        request_sha256=fingerprint, issue_id=issue_id, created_at=datetime.now(UTC),
        result=c.ToolResult[c.EntityResult](outcome="OK", data=c.EntityResult(
            record_id=record_id, state_revision=state_revision), event_ids=event_ids))


def _record_event_ids(store: Store, issue_id: str, record_id: str) -> tuple[int, ...]:
    return tuple(event["id"] for event in store.events(issue_id)
                 if event["payload"].get("record_id") == record_id)


def _proposal_payload(fact: c.ClassificationFact | c.JurisdictionFact) -> dict:
    """Only caller-visible proposal fields participate in retries, never server clocks/revisions."""
    payload = fact.model_dump(mode="json")
    for field in ("id", "source_issue_revision", "fact_version", "created_at", "provenance", "metadata", "proposed_by"):
        payload.pop(field)
    return payload


def create_issue_from_signal(store: Store, *, signal_id: str, rationale: str,
                             context: c.MutationContext) -> c.RequestReceipt:
    """Service-only operation: atomically create and canonical-link a new candidate case."""
    _authorize(store, context, signal_id=signal_id)
    signal = store.get_signal(signal_id)
    if signal.effective_source_role == "official_record":
        raise ValueError("official record cannot create a physical-observation issue")
    fingerprint = request_fingerprint({"signal_id": signal_id, "rationale": rationale,
        "actor": context.actor.model_dump(mode="json"), "expected_revision": context.expected_revision})
    issue_id = stable_id("issue", context.actor.actor_id, context.idempotency_key)
    with store.transaction() as tx:
        _authorize(store, context, signal_id=signal_id)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            return previous
        linked = store.issue_for_signal(signal_id)
        if linked is not None:
            raise IdempotencyConflict("signal is already linked to an issue")
        store.db.execute(
            "INSERT INTO issues(id,category,location,status,evidence_score,score_json,created_at,"
            "state_revision,hazards_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (issue_id, "unclassified", signal.reported_location, "CANDIDATE", 0,
             json.dumps({"components": {"image": 0, "independent_sources": 0,
                 "precise_geocode": 0, "service_match": 0, "persistence": 0},
                 "total": 0, "threshold": 70, "actionable": False}, sort_keys=True),
             datetime.now(UTC).isoformat(), 0, "[]"),
        )
        created = _event(tx, issue_id, context.actor, "ISSUE_CREATED_FROM_SIGNAL", revision=0,
            summary=rationale, record_id=signal_id)
        linked_issue = store._link_signal(issue_id, signal_id)
        _bind_unlinked_signal_invocation(tx, store, context, signal_id=signal_id, issue_id=issue_id)
        result = c.RequestReceipt(id=str(uuid4()), operation=context.operation,
            invocation_id=context.invocation_id,
            actor_id=context.actor.actor_id, idempotency_key=context.idempotency_key,
            request_sha256=fingerprint, signal_id=signal_id, issue_id=issue_id,
            created_at=datetime.now(UTC), result=c.ToolResult[c.EntityResult](outcome="OK",
                data=c.EntityResult(record_id=issue_id, state_revision=linked_issue["state_revision"]),
                event_ids=(created.id,)))
        tx.save_request(result)
        return result


def link_signal_to_issue(store: Store, *, issue_id: str, signal_id: str, rationale: str,
                         context: c.MutationContext) -> c.RequestReceipt:
    """Save one explicit candidate match; no text/location heuristic silently merges cases."""
    fingerprint = request_fingerprint({"issue_id": issue_id, "signal_id": signal_id,
        "rationale": rationale, "actor": context.actor.model_dump(mode="json"),
        "expected_revision": context.expected_revision})
    def authorize_link():
        if store.issue_for_signal(signal_id) is None:
            return _authorize_unlinked_signal_transition(store, context, issue_id=issue_id, signal_id=signal_id)
        return _authorize(store, context, issue_id=issue_id, signal_id=signal_id)

    authorize_link()
    with store.transaction() as tx:
        authorize_link()
        _expected(context)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            return previous
        tx.require_issue(issue_id, context.expected_revision)
        linked = store.issue_for_signal(signal_id)
        if linked is not None:
            raise IdempotencyConflict("signal is already linked to an issue")
        result = store._link_signal(issue_id, signal_id)
        _bind_unlinked_signal_invocation(tx, store, context, signal_id=signal_id, issue_id=issue_id)
        current = store.get_issue_record(issue_id)
        event = _event(tx, issue_id, context.actor, "CANDIDATE_LINK_RECORDED",
            revision=current.state_revision, summary=rationale, record_id=signal_id)
        receipt = c.RequestReceipt(id=str(uuid4()), operation=context.operation,
            invocation_id=context.invocation_id,
            actor_id=context.actor.actor_id, idempotency_key=context.idempotency_key,
            request_sha256=fingerprint, signal_id=signal_id, issue_id=issue_id,
            created_at=datetime.now(UTC), result=c.ToolResult[c.EntityResult](outcome="OK",
                data=c.EntityResult(record_id=issue_id, state_revision=result["state_revision"]),
                event_ids=(event.id,)))
        tx.save_request(receipt)
        return receipt


def record_geocode(store: Store, *, issue_id: str, signal_id: str, result: GeocodeResult,
                   context: c.MutationContext) -> tuple[c.GeocodeFact, c.RequestReceipt]:
    fingerprint = request_fingerprint({"issue_id": issue_id, "signal_id": signal_id,
        "actor": context.actor.model_dump(mode="json"),
        "expected_revision": context.expected_revision})
    with store.transaction() as tx:
        _authorize(store, context, issue_id=issue_id, signal_id=signal_id)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            saved = previous.result.data
            assert isinstance(saved, c.EntityResult)
            return store.get_geocode_fact(saved.record_id), previous
        issue = tx.require_issue(issue_id, context.expected_revision)
        if store.issue_for_signal(signal_id) != issue:
            raise ValueError("geocode signal is not linked to issue")
        prior = [store.get_geocode_fact(row[0]) for row in store.db.execute(
            "SELECT id FROM geocode_facts WHERE issue_id=? AND signal_id=?", (issue_id, signal_id)
        )]
        if prior:
            fact = max(prior, key=lambda item: item.fact_version)
            receipt = _receipt(context=context, fingerprint=fingerprint, issue_id=issue_id,
                record_id=fact.id, state_revision=issue.state_revision,
                event_ids=_record_event_ids(store, issue_id, fact.id))
            tx.save_request(receipt)
            return fact, receipt
        result = result() if callable(result) else result
        fact = c.GeocodeFact(id=stable_id("geocode", issue_id, signal_id), issue_id=issue_id,
            signal_id=signal_id, outcome=result.outcome, location=result.location,
            source_mode=result.source_mode, looked_up_at=datetime.now(UTC), provenance="seeded",
            source_issue_revision=issue.state_revision, fact_version=_fact_version(store, issue_id), error_code=result.error_code,
            created_at=datetime.now(UTC))
        tx.insert_geocode_fact(fact)
        store.db.execute("UPDATE issues SET geocode_json=? WHERE id=?",
                         (fact.location.model_dump_json() if fact.location else None, issue_id))
        score = store._refresh_score(issue_id)
        refreshed = store.get_issue_record(issue_id)
        event = _event(tx, issue_id, context.actor,
            "GEOCODE_RECORDED" if fact.outcome == "MATCH" else "GEOCODE_UNRESOLVED",
            revision=refreshed.state_revision, summary="trusted geocode lookup recorded", record_id=fact.id,
            score=c.EvidenceComponents(**score["components"]), outcome="OK" if fact.outcome == "MATCH" else "NEEDS_REVIEW")
        receipt = _receipt(context=context, fingerprint=fingerprint, issue_id=issue_id,
            record_id=fact.id, state_revision=store.get_issue_record(issue_id).state_revision,
            event_ids=(event.id,))
        tx.save_request(receipt)
        return fact, receipt


def record_service_lookup(store: Store, *, issue_id: str, signal_id: str, result: ServiceResult,
                          context: c.MutationContext) -> tuple[c.ServiceLookupRecord, c.RequestReceipt]:
    _authorize(store, context, issue_id=issue_id, signal_id=signal_id)
    signal = store.get_signal(signal_id)
    if signal.effective_source_role == "official_record":
        raise ValueError("official records cannot trigger a service lookup")
    fingerprint = request_fingerprint({"issue_id": issue_id, "signal_id": signal_id,
        "actor": context.actor.model_dump(mode="json"),
        "expected_revision": context.expected_revision})
    with store.transaction() as tx:
        _authorize(store, context, issue_id=issue_id, signal_id=signal_id)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            saved = previous.result.data
            assert isinstance(saved, c.EntityResult)
            return store.get_service_lookup(saved.record_id), previous
        issue = tx.require_issue(issue_id, context.expected_revision)
        if store.issue_for_signal(signal_id) != issue:
            raise ValueError("lookup signal is not linked to issue")
        existing = store.db.execute("SELECT id FROM service_lookups WHERE issue_id=? AND signal_id=?",
                                    (issue_id, signal_id)).fetchone()
        if existing:
            lookup = store.get_service_lookup(existing[0])
            receipt = _receipt(context=context, fingerprint=fingerprint, issue_id=issue_id,
                record_id=lookup.id, state_revision=issue.state_revision,
                event_ids=_record_event_ids(store, issue_id, lookup.id))
            tx.save_request(receipt)
            return lookup, receipt
        result = result() if callable(result) else result
        lookup = c.ServiceLookupRecord(id=stable_id("lookup", issue_id, signal_id), issue_id=issue_id,
            signal_id=signal_id, outcome=result.outcome, external_record_id=result.external_record_id,
            status=result.status, completed_at=result.completed_at, looked_up_at=datetime.now(UTC),
            provenance="seeded", source_mode=result.source_mode, error_code=result.error_code)
        tx.insert_service_lookup(lookup)
        record = None
        if lookup.outcome == "MATCH":
            previous_record = store.get_issue(issue_id)["service_record"]
            keep_dispute = (previous_record is not None and previous_record["id"] == lookup.external_record_id
                and previous_record["status"] == lookup.status and previous_record["conflict"] == "disputed"
                and ServiceRecord.from_dict(previous_record).completed_at == lookup.completed_at)
            record = ServiceRecord(id=lookup.external_record_id, status=lookup.status,
                provenance=lookup.provenance, completed_at=lookup.completed_at,
                conflict="disputed" if keep_dispute else "pending" if lookup.status == "COMPLETED" else "none")
        store.db.execute("UPDATE issues SET service_record_json=? WHERE id=?",
                         (json.dumps(record.to_dict(), sort_keys=True) if record else None, issue_id))
        score = store._refresh_score(issue_id)
        current = store.get_issue_record(issue_id)
        event = _event(tx, issue_id, context.actor,
            "SERVICE_LOOKUP_RECORDED" if record else "SERVICE_LOOKUP_UNRESOLVED", revision=current.state_revision,
            summary="trusted service lookup recorded", record_id=lookup.id,
            score=c.EvidenceComponents(**score["components"]),
            outcome="NEEDS_REVIEW" if lookup.outcome == "UNAVAILABLE" else "OK")
        receipt = _receipt(context=context, fingerprint=fingerprint, issue_id=issue_id,
            record_id=lookup.id, state_revision=store.get_issue_record(issue_id).state_revision,
            event_ids=(event.id,))
        tx.save_request(receipt)
        return lookup, receipt


def save_classification(store: Store, fact: c.ClassificationFact, *,
                        context: c.MutationContext) -> tuple[c.ClassificationFact, c.RequestReceipt]:
    fingerprint = request_fingerprint({"fact": _proposal_payload(fact),
        "actor": context.actor.model_dump(mode="json"), "expected_revision": context.expected_revision})
    with store.transaction() as tx:
        _authorize(store, context, issue_id=fact.issue_id, signal_id=fact.signal_id)
        _expected(context)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            saved = previous.result.data
            assert isinstance(saved, c.EntityResult)
            return store.get_classification_fact(saved.record_id), previous
        issue = tx.require_issue(fact.issue_id, context.expected_revision)
        if store.issue_for_signal(fact.signal_id) != issue:
            raise ValueError("classification signal is not linked to issue")
        if fact.source_issue_revision != issue.state_revision:
            raise ValueError("classification fact must name the current issue revision")
        for evidence_id in fact.supporting_evidence_ids:
            try:
                links = store.evidence_associations(evidence_id)
            except KeyError:
                raise ValueError("classification evidence does not exist") from None
            if not any(link.issue_id == issue.id or (
                link.signal_id is not None and store.issue_for_signal(link.signal_id) == issue
            ) for link in links):
                raise ValueError("classification evidence does not belong to issue")
            _authorize(store, context, issue_id=issue.id, evidence_ids=(evidence_id,))
        fact = fact.model_copy(update={"fact_version": _fact_version(store, issue.id),
            "proposed_by": context.actor, "metadata": None,
            "provenance": _provenance([store.get_signal(fact.signal_id).provenance,
                *(store.get_evidence(e).provenance for e in fact.supporting_evidence_ids)]),
            "created_at": datetime.now(UTC)})
        tx.insert_classification_fact(fact)
        updated = issue.model_copy(update={"category": fact.category,
                                           "hazards": store.current_issue_facts(issue.id).unresolved_hazards,
                                           "state_revision": issue.state_revision + 1})
        tx.replace_issue(updated, issue.state_revision)
        event = _event(tx, issue.id, context.actor, "CLASSIFICATION_RECORDED", revision=updated.state_revision,
            summary="classification proposal saved", record_id=fact.id)
        receipt = _receipt(context=context, fingerprint=fingerprint, issue_id=issue.id,
            record_id=fact.id, state_revision=updated.state_revision, event_ids=(event.id,))
        tx.save_request(receipt)
        return fact, receipt


def save_jurisdiction(store: Store, fact: c.JurisdictionFact, *,
                      context: c.MutationContext) -> tuple[c.JurisdictionFact, c.RequestReceipt]:
    fingerprint = request_fingerprint({"fact": _proposal_payload(fact),
        "actor": context.actor.model_dump(mode="json"), "expected_revision": context.expected_revision})
    with store.transaction() as tx:
        _authorize(store, context, issue_id=fact.issue_id)
        _expected(context)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            saved = previous.result.data
            assert isinstance(saved, c.EntityResult)
            return store.get_jurisdiction_fact(saved.record_id), previous
        issue = tx.require_issue(fact.issue_id, context.expected_revision)
        if fact.source_issue_revision != issue.state_revision:
            raise ValueError("jurisdiction fact must name the current issue revision")
        current_facts = store.current_issue_facts(issue.id)
        if current_facts.classification is None or current_facts.classification.id != fact.classification_fact_id:
            raise ValueError("jurisdiction requires current classification")
        current_ids = {f.id for f in (current_facts.classification, current_facts.geocode) if f is not None}
        if not set(fact.supporting_fact_ids) <= current_ids:
            raise ValueError("jurisdiction requires current supporting facts")
        for reference in fact.supporting_fact_ids:
            try:
                valid = store.get_geocode_fact(reference).issue_id == issue.id
            except KeyError:
                try:
                    valid = store.get_classification_fact(reference).issue_id == issue.id
                except KeyError:
                    valid = False
            if not valid:
                raise ValueError("jurisdiction support does not belong to issue")
        fact = fact.model_copy(update={"fact_version": _fact_version(store, issue.id),
            "proposed_by": context.actor, "metadata": None, "created_at": datetime.now(UTC),
            "provenance": _provenance([current_facts.classification.provenance,
                *(f.provenance for f in (current_facts.geocode,) if f is not None and f.id in fact.supporting_fact_ids)])})
        tx.insert_jurisdiction_fact(fact)
        updated = issue.model_copy(update={"responsibility": fact.responsibility,
                                           "state_revision": issue.state_revision + 1})
        tx.replace_issue(updated, issue.state_revision)
        event = _event(tx, issue.id, context.actor, "JURISDICTION_RECORDED", revision=updated.state_revision,
            summary="jurisdiction proposal saved", record_id=fact.id)
        receipt = _receipt(context=context, fingerprint=fingerprint, issue_id=issue.id,
            record_id=fact.id, state_revision=updated.state_revision, event_ids=(event.id,))
        tx.save_request(receipt)
        return fact, receipt


_B4_DECISION_TYPES = frozenset(("MONITOR", "MARK_ACTIONABLE", "DISPUTE_OFFICIAL_STATUS",
                                "ROUTE_EXTERNAL", "REQUEST_OPERATOR"))
_APPLIED_DECISION_TYPES = frozenset(("MONITOR", "MARK_ACTIONABLE",
                                     "DISPUTE_OFFICIAL_STATUS", "ROUTE_EXTERNAL"))


def _decision_gates(store: Store, issue: c.IssueRecord,
                    proposed_type: c.DecisionType) -> tuple[tuple[c.GateRecord, ...], str, str]:
    """Validate one requested B4 decision. Several safe intents can be valid together."""
    if proposed_type not in _B4_DECISION_TYPES:
        raise ValueError("decision type belongs to a later card")
    facts = store.current_issue_facts(issue.id)
    classification, jurisdiction = facts.classification, facts.jurisdiction
    route = (route_category(load_policy(), classification.category, facts.unresolved_hazards)
             if classification is not None else "review")
    record = store.get_issue(issue.id)["service_record"]
    service = ServiceRecord.from_dict(record) if record else None
    if proposed_type == "REQUEST_OPERATOR":
        return (c.GateRecord(name="operator_review", allowed=True),), "operator", "request_operator"
    if proposed_type == "MONITOR":
        return (c.GateRecord(name="evidence_threshold", allowed=issue.evidence_score >= 70,
                             unmet=() if issue.evidence_score >= 70 else (
                                 "another_independent_observation_or_fresh_persistence",)),), \
            "service", "await_observation"
    if proposed_type == "MARK_ACTIONABLE":
        unmet = []
        if classification is None or jurisdiction is None:
            unmet.append("current_facts_missing")
        elif route != "autonomous" or jurisdiction.responsibility != "district":
            unmet.append("ordinary_cleanup_not_authorized")
        elif facts.unresolved_hazards or classification.unknowns or jurisdiction.unknowns:
            unmet.append("hazard_review_required")
        if issue.evidence_score < 70:
            unmet.append("evidence_threshold")
        if unmet:
            raise ValueError("MARK_ACTIONABLE gate failed: " + ",".join(unmet))
        return (c.GateRecord(name="actionable", allowed=True),), "service", "build_resolution_plan"
    if proposed_type == "ROUTE_EXTERNAL":
        if classification is None or jurisdiction is None or route != "city" or jurisdiction.responsibility != "city":
            raise ValueError("ROUTE_EXTERNAL requires current city routing facts")
        return (c.GateRecord(name="external_route", allowed=True),), "service", "route_external"
    if service is None or service.status != "COMPLETED" or not dispute_supported(store._signals(issue.id), service):
        raise ValueError("DISPUTE_OFFICIAL_STATUS requires two independent newer observations")
    return (c.GateRecord(name="official_dispute", allowed=True),), "service", "record_official_dispute"


def decide(store: Store, *, issue_id: str, proposed_type: c.DecisionType, summary: str,
           evidence_ids: tuple[str, ...], context: c.MutationContext) -> c.DecisionRecord:
    """Persist a model/service intent after policy gates; intent never mutates issue state."""
    fingerprint = request_fingerprint({"issue_id": issue_id, "decision_type": proposed_type,
        "summary": summary, "evidence_ids": evidence_ids, "actor": context.actor.model_dump(mode="json"),
        "expected_revision": context.expected_revision})
    with store.transaction() as tx:
        trigger = _authorize(store, context, issue_id=issue_id)
        _expected(context)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            saved = previous.result.data
            assert isinstance(saved, c.EntityResult)
            return store.get_decision(saved.record_id)
        issue = tx.require_issue(issue_id, context.expected_revision)
        _action_lifecycle(store, issue)
        gates, next_actor, next_event = _decision_gates(store, issue, proposed_type)
        if proposed_type == "MONITOR":
            summary = (f"{summary} Next evidence: another independent observation or a fresh "
                       "same-reporter image at least 24 hours later.")
        available_evidence = {
            evidence.id for signal_id in issue.signal_ids
            for evidence in store.evidence_for_entity(signal_id=signal_id)
        }
        if not set(evidence_ids) <= available_evidence:
            raise ValueError("decision evidence does not belong to issue")
        if trigger is None:
            trigger = _event(tx, issue_id, context.actor, "INVESTIGATION_REQUESTED",
                revision=issue.state_revision, summary="Direct service investigation request")
        decision = c.DecisionRecord(id=stable_id("decision", issue_id, context.actor.actor_id,
            context.operation, context.idempotency_key), issue_id=issue_id,
            trigger_event_id=trigger.id, invocation_id=context.invocation_id, decision_type=proposed_type, summary=summary,
            evidence_ids=evidence_ids, score_components=issue.components, policy_version=POLICY_VERSION,
            gate_results=gates, next_actor=next_actor, next_event=next_event, created_at=datetime.now(UTC))
        tx.append_decision(decision)
        event = _event(tx, issue_id, context.actor, "INVESTIGATION_DECIDED",
            revision=issue.state_revision, summary=summary, record_id=decision.id)
        tx.save_request(_receipt(context=context, fingerprint=fingerprint, issue_id=issue_id,
            record_id=decision.id, state_revision=issue.state_revision, event_ids=(event.id,)))
        return decision


def apply_investigation_decision(store: Store, *, issue_id: str, decision_id: str,
                                 context: c.MutationContext) -> c.RequestReceipt:
    """Apply a saved B4 decision once, after a fresh revision and gate recheck."""
    if context.expected_revision is None:
        raise ValueError("investigation action requires expected revision")
    fingerprint = request_fingerprint({"issue_id": issue_id, "decision_id": decision_id,
        "actor": context.actor.model_dump(mode="json"), "expected_revision": context.expected_revision})
    with store.transaction() as tx:
        _authorize(store, context, issue_id=issue_id)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            return previous
        issue = tx.require_issue(issue_id, context.expected_revision)
        _action_lifecycle(store, issue)
        decision = store.get_decision(decision_id)
        if decision.issue_id != issue_id or decision.decision_type not in _APPLIED_DECISION_TYPES:
            raise ValueError("decision cannot be applied by investigation action")
        _decision_gates(store, issue, decision.decision_type)
        current = issue
        if decision.decision_type == "DISPUTE_OFFICIAL_STATUS":
            raw = store.get_issue(issue_id)["service_record"]
            assert raw is not None
            store.db.execute("UPDATE issues SET service_record_json=? WHERE id=?", (
                json.dumps(replace(ServiceRecord.from_dict(raw), conflict="disputed").to_dict(), sort_keys=True),
                issue_id))
            store._refresh_score(issue_id)
            current = store.get_issue_record(issue_id)
        status = {
            "MONITOR": "MONITORING", "MARK_ACTIONABLE": "ACTIONABLE",
            "ROUTE_EXTERNAL": "ROUTED_EXTERNAL",
        }.get(decision.decision_type, current.status)
        if decision.decision_type == "DISPUTE_OFFICIAL_STATUS":
            updated = current  # the cache/score update already advanced this transaction's revision
        else:
            updated = current.model_copy(update={"status": status, "state_revision": current.state_revision + 1})
            tx.replace_issue(updated, current.state_revision)
        event = _event(tx, issue_id, context.actor, "INVESTIGATION_ACTION_APPLIED",
            revision=updated.state_revision, summary=decision.summary, record_id=decision.id,
            score=updated.components)
        receipt = _receipt(context=context, fingerprint=fingerprint, issue_id=issue_id,
            record_id=decision.id, state_revision=updated.state_revision, event_ids=(event.id,))
        tx.save_request(receipt)
        return receipt


def inspection_cache_key(*, evidence: c.EvidenceRecord, preprocessing_version: str, schema_version: str,
                         prompt_version: str, request_version: str, configuration_version: str,
                         model_id: str, region: str) -> str:
    return hashlib.sha256(json.dumps({"sha256": evidence.image_sha256,
        "preprocessing_version": preprocessing_version, "schema_version": schema_version,
        "prompt_version": prompt_version, "request_version": request_version,
        "configuration_version": configuration_version, "model_id": model_id, "region": region},
        sort_keys=True).encode()).hexdigest()


def intake_configuration_version() -> str:
    return hashlib.sha256(json.dumps({"model": settings.resolved_vision_model_id,
        "region": settings.region, "profile": _inspection_profile(),
        "max_tokens": INTAKE_MAX_TOKENS, "temperature": 0}, sort_keys=True).encode()).hexdigest()[:16]


def _inspection_basis(image):
    config = intake_configuration_version()
    return c.IntakeInspectionBasis(
        cache_key=inspection_cache_key(evidence=image, preprocessing_version=INTAKE_PREPROCESSING_VERSION,
            schema_version=INTAKE_SCHEMA_VERSION, prompt_version=INTAKE_PROMPT_VERSION,
            request_version=INTAKE_REQUEST_VERSION, configuration_version=config,
            model_id=settings.resolved_vision_model_id, region=settings.region),
        model_id=settings.resolved_vision_model_id, region=settings.region, profile=_inspection_profile(),
        preprocessing_version=INTAKE_PREPROCESSING_VERSION, schema_version=INTAKE_SCHEMA_VERSION,
        prompt_version=INTAKE_PROMPT_VERSION, request_version=INTAKE_REQUEST_VERSION,
        configuration_version=config)


def _inspection_profile():
    # Preserve no named profile as ambient credentials for IAM-role hosts.
    return os.getenv("AWS_PROFILE") or os.getenv("AWS_DEFAULT_PROFILE")


def default_intake_inspector(image: bytes, *, basis: c.IntakeInspectionBasis) -> dict:
    """One frozen configured request; SDK retries are disabled for honest attempt accounting."""
    from botocore.config import Config

    from .aws_session import frozen_boto3_session

    session = frozen_boto3_session(basis.profile)
    client = session.client("bedrock-runtime", region_name=basis.region,
        config=Config(connect_timeout=10, read_timeout=90, retries={"total_max_attempts": 1}))
    request = json.loads(json.dumps(INTAKE_REQUEST_TEMPLATE))
    request["messages"][0]["content"][0]["image"]["source"]["bytes"] = image
    response = client.converse(modelId=basis.model_id, **request)
    uses = [block["toolUse"] for block in response.get("output", {}).get("message", {}).get("content", [])
            if "toolUse" in block]
    valid = response.get("stopReason") == "tool_use" and len(uses) == 1 and uses[0].get("name") == "report_intake_findings"
    return {"findings": uses[0].get("input") if valid else None,
        "request_id": response.get("ResponseMetadata", {}).get("RequestId"),
        "usage": response.get("usage"), "metrics": response.get("metrics"),
        "stop_reason": response.get("stopReason")}


def _inspection_record(*, signal_id, image, basis, claim_id=None, findings=None, metadata=None,
                       error_code=None, cached_from_id=None, cache_eligible=False):
    return c.IntakeInspectionRecord(id=str(uuid4()), signal_id=signal_id,
        evidence_id=image.id, evidence_sha256=image.image_sha256, cache_key=basis.cache_key,
        outcome="SUCCESS" if error_code is None else "ERROR", findings=findings, metadata=metadata,
        error_code=error_code, claim_id=claim_id, cached_from_id=cached_from_id,
        cache_eligible=cache_eligible, model_id=basis.model_id, region=basis.region, profile=basis.profile,
        preprocessing_version=basis.preprocessing_version, schema_version=basis.schema_version,
        prompt_version=basis.prompt_version, request_version=basis.request_version,
        configuration_version=basis.configuration_version, created_at=datetime.now(UTC))


def _save_inspection(store, tx, record, context, fingerprint, *, save_receipt=True):
    tx.insert_intake_inspection(record)
    issue = store.issue_for_signal(record.signal_id)
    if issue is not None:
        hazards = store.current_issue_facts(issue.id).unresolved_hazards
        if hazards != issue.hazards:
            tx.replace_issue(issue.model_copy(update={"hazards": hazards,
                "state_revision": issue.state_revision + 1}), issue.state_revision)
    event = tx.append_event(c.NewEvent(issue_id=issue.id if issue else None, signal_id=record.signal_id,
        invocation_id=context.invocation_id,
        event_type="INTAKE_INSPECTED" if record.outcome == "SUCCESS" else "INTAKE_INSPECTION_FAILED",
        timestamp=datetime.now(UTC), actor=context.actor, policy_version=POLICY_VERSION,
        payload=c.EventFacts(record_id=record.id, outcome="OK" if record.outcome == "SUCCESS" else "ERROR",
            reason_code=record.error_code, evidence_ids=(record.evidence_id,), metadata=record.metadata)))
    result = c.ToolResult[c.EntityResult](outcome="OK" if record.outcome == "SUCCESS" else "ERROR",
        reason_code=record.error_code, data=c.EntityResult(record_id=record.id),
        evidence_ids=(record.evidence_id,), event_ids=(event.id,))
    if save_receipt:
        tx.save_request(c.RequestReceipt(id=str(uuid4()), operation=context.operation,
            invocation_id=context.invocation_id,
            actor_id=context.actor.actor_id, idempotency_key=context.idempotency_key,
            request_sha256=fingerprint, signal_id=record.signal_id, issue_id=issue.id if issue else None,
            created_at=datetime.now(UTC), result=result))
    return result


def _abandon_inspection(store, tx, claim):
    """A crashed/expired call may have spent tokens; its missing result is explicitly unknown."""
    context = c.MutationContext(actor=claim.actor, operation=claim.operation,
        idempotency_key=claim.idempotency_key, invocation_id=claim.invocation_id)
    record = _inspection_record(signal_id=claim.signal_id, image=store.get_evidence(claim.evidence_id),
        basis=claim.basis, claim_id=claim.id, error_code="INSPECTION_INTERRUPTED")
    tx.finish_intake_claim(claim.id, abandoned=True)
    return _save_inspection(store, tx, record, context, claim.request_sha256)


def inspect_intake_photo(store: Store, *, signal_id: str, image_root, inspector=None,
                         context: c.MutationContext | None = None) -> c.ToolResult[c.EntityResult]:
    """Claim under a short writer lock, inspect outside it, then atomically save an owned result."""
    _authorize(store, context, signal_id=signal_id)
    fingerprint = request_fingerprint({"signal_id": signal_id, "expected_revision": context.expected_revision})
    with store.transaction() as tx:
        _authorize(store, context, signal_id=signal_id)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            return previous.result
        own_claim = store.intake_claim_for_request(context)
        if own_claim is not None:
            if own_claim.request_sha256 != fingerprint:
                raise IdempotencyConflict("idempotency key payload conflict")
            if own_claim.status == "RUNNING" and own_claim.expires_at <= datetime.now(UTC):
                return _abandon_inspection(store, tx, own_claim)
            return c.ToolResult(outcome="ERROR", reason_code="INSPECTION_IN_PROGRESS")
        evidence = store.evidence_for_entity(signal_id=signal_id)
        if not evidence:
            return c.ToolResult(outcome="NOT_FOUND", reason_code="NO_IMAGE")
        image = evidence[0]
        _authorize(store, context, signal_id=signal_id, evidence_ids=(image.id,))
        basis = _inspection_basis(image)
        cached = store.find_intake_inspection(basis.cache_key)
        if cached is not None:
            record = _inspection_record(signal_id=signal_id, image=image, basis=basis,
                findings=cached.findings, cached_from_id=cached.id)
            return _save_inspection(store, tx, record, context, fingerprint)
        running = store.running_intake_claim(basis.cache_key)
        if running is not None:
            if running.expires_at > datetime.now(UTC):
                return c.ToolResult(outcome="ERROR", reason_code="INSPECTION_IN_PROGRESS")
            _abandon_inspection(store, tx, running)
        now = datetime.now(UTC)
        claim = c.IntakeInspectionClaim(id=str(uuid4()), actor=context.actor,
            operation=context.operation, idempotency_key=context.idempotency_key,
            invocation_id=context.invocation_id,
            request_sha256=fingerprint, signal_id=signal_id, evidence_id=image.id,
            evidence_sha256=image.image_sha256, cache_key=basis.cache_key, basis=basis,
            started_at=now, expires_at=now + timedelta(seconds=120))
        tx.insert_intake_claim(claim)

    findings, metadata, error_code = None, None, None
    try:
        bytes_ = ImageStorage(image_root).open(image.image_ref)
        if hashlib.sha256(bytes_).hexdigest() != image.image_sha256 or len(bytes_) != image.size_bytes:
            raise ValueError("STORED_IMAGE_MISMATCH")
        metadata = c.ModelRunMetadata(role="image", model_id=basis.model_id, vision_model_id=basis.model_id,
            region=basis.region, prompt_version=basis.prompt_version, attempt_count=1)
        answer = inspector(bytes_) if inspector is not None else default_intake_inspector(bytes_, basis=basis)
        if isinstance(answer, dict):
            metadata = metadata.model_copy(update={
                "request_id": answer.get("request_id"),
                "stop_reason": answer.get("stop_reason"),
                "usage": c.ModelUsage.model_validate(answer["usage"]) if answer.get("usage") else None,
                "metrics": c.ModelMetrics.model_validate(answer["metrics"]) if answer.get("metrics") else None})
        findings = answer if isinstance(answer, c.IntakePhotoFindings) else c.IntakePhotoFindings.model_validate_json(
            json.dumps(answer.get("findings", answer), allow_nan=False))
    except Exception as exc:  # noqa: BLE001 -- bounded errors preserve the attempt without fabricated findings
        error_code = ("STORED_IMAGE_MISMATCH" if str(exc) == "STORED_IMAGE_MISMATCH"
                      else "INVALID_MODEL_OUTPUT" if isinstance(exc, (ValueError, TypeError))
                      else "INSPECTION_FAILED")

    # Preserve a returned physical observation even if the runtime owner was replaced.
    observed = _inspection_record(signal_id=signal_id, image=image, basis=basis, claim_id=claim.id,
        findings=findings, metadata=metadata, error_code=error_code)
    with store.transaction():
        store.db.execute("INSERT INTO intake_physical_observations VALUES (?,?)", (claim.id, observed.model_dump_json()))
    with store.transaction() as tx:
        current = store.get_intake_claim(claim.id)
        tx.validate_runtime(context)
        _authorize(store, context, signal_id=signal_id, evidence_ids=(image.id,))
        if current.status == "RUNNING" and current.expires_at <= datetime.now(UTC):
            _abandon_inspection(store, tx, current)
            current = store.get_intake_claim(claim.id)
        owned = current.status == "RUNNING"
        record = _inspection_record(signal_id=signal_id, image=image, basis=basis, claim_id=claim.id,
            findings=findings, metadata=metadata, error_code=error_code,
            cache_eligible=owned and error_code is None)
        if owned:
            tx.finish_intake_claim(claim.id)
        result = _save_inspection(store, tx, record, context, fingerprint, save_receipt=owned)
        if not owned:
            # Fenced late result retains actual usage but cannot replace the interrupted receipt/cache.
            result = store.request_for_operation(context).result
    _authorize(store, context, signal_id=signal_id, evidence_ids=(image.id,))
    return result
