"""Server-owned, consistent case snapshots. Reads never repair or rebind a cause."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import case_contracts as v
from . import contracts as c
from .actors import AccessBoundary, AccessError, Action
from .config import settings
from .investigation import _validated_cause
from .operations import exception_detail
from .policy import load_policy
from .prompts import PROMPT_VERSION
from .store import Store
from .tools.protocol import SCHEMA_VERSION

EFFECTS = {"INVESTIGATION_ACTION_APPLIED", "SIMULATED_DISPATCH", "REWORK_REQUIRED",
           "EXCEPTION_RAISED", "ISSUE_RESOLVED", "JOB_CANCELLED"}


def _project(model, record, **updates):
    data = record.model_dump() if isinstance(record, c.Record) else record
    return model(**{name: data[name] for name in model.model_fields if name in data} | updates)


def _event(store, event_id):
    row = dict(store.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone())
    payload = json.loads(row["payload"])
    actor = json.loads(row["actor_json"]) if row.get("actor_json") else {}
    # Legacy events have untyped payloads: only their envelope is projected.
    safe = {name: payload[name] for name in (
        "summary", "outcome", "reason_code", "record_id", "submission_id", "decision_id",
        "exception_id", "evidence_ids", "unmet", "gate_results") if name in payload} if actor else {}
    data = {name: row[name] for name in v.EventSummary.model_fields if name in row}
    data.update(safe, actor_type=actor.get("actor_type"))
    if data.get("summary"):
        data["summary"] = data["summary"][:1200]
    return v.EventSummary.model_validate_json(json.dumps(data))


def _signal(store, signal_id):
    signal = store.get_signal(signal_id)
    return _project(v.SignalContext, signal.to_dict(), source_role=signal.effective_source_role,
        observed_at=signal.observed_at, received_at=signal.received_at,
        evidence_ids=tuple(x.id for x in store.evidence_for_entity(signal_id=signal_id)))


def _cursor(value, count, defaults):
    if value is None:
        return defaults
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){" + str(count - 1) + "}", value) or len(value) > 100:
        raise ValueError("invalid context cursor")
    return tuple(int(x) for x in value.split("."))


def build_context(store: Store, trigger_event_id: int, *, actor: c.ActorContext,
                  district_id: str, invocation_id: str, policy_path: Path = Path("data/policy.yaml"),
                  candidates_cursor: str | None = None, events_cursor: str | None = None) -> v.CaseContext:
    boundary = AccessBoundary(actor, district_id)
    boundary.require(Action.READ_CONTEXT)
    if actor.actor_type != "service":
        raise AccessError(403, "ROLE_FORBIDDEN")
    policy = load_policy(policy_path)
    if policy["district"] != district_id:
        raise ValueError("configured policy district mismatch")
    with store.read_snapshot():
        invocation = store.invocation_for_event(trigger_event_id)
        if invocation.id != invocation_id:
            raise AccessError(403, "INVOCATION_FORBIDDEN")
        trigger = _validated_cause(store, c.MutationContext(actor=actor,
            operation="read_case_context", idempotency_key="read-only", invocation_id=invocation.id),
            issue_id=invocation.issue_id, signal_id=invocation.signal_id, job_id=invocation.job_id)
        issue = boundary._issue(store, invocation.issue_id) if invocation.issue_id else None
        if invocation.signal_id:
            boundary.signal(store, invocation.signal_id)
        if invocation.job_id:
            job = boundary.require_job(store, invocation.job_id)
            proof = store.get_submission(trigger.payload.submission_id)
            if proof.job_id != job.id or proof.issue_id != issue.id:
                raise ValueError("trigger proof ownership mismatch")
            if trigger.event_type == "PROOF_SUBMITTED":
                if store.proof_event_for_submission(proof.id).id != trigger.id:
                    raise ValueError("trigger proof event mismatch")
            else:
                decision = store.get_operator_decision(trigger.payload.decision_id)
                exception = store.get_exception(decision.exception_id)
                if (decision.job_id != job.id or decision.submission_id != proof.id
                        or decision.issue_id != issue.id or exception.id != trigger.payload.exception_id
                        or exception.submission_id != proof.id
                        or store.invocation_for_decision(decision.id).id != invocation.id):
                    raise ValueError("operator cause ownership mismatch")
        signal_ids = issue.signal_ids if issue else (invocation.signal_id,)
        signals = tuple(_signal(store, signal_id) for signal_id in signal_ids if signal_id)
        facts = store.current_issue_facts(issue.id) if issue else None
        score = store.current_evidence_score(issue.id) if issue else None
        plans = tuple(store.plans_for_issue(issue.id)) if issue else ()
        jobs = store.jobs_for_issue(issue.id) if issue else ()
        reservations, payments, submissions, verifications, evidence = [], [], {}, {}, {}
        exception_ids = set()
        if issue:
            rows = store.exceptions_for_issue(issue.id, limit=100)
            exception_ids.update(x.id for x in rows if x.status in {"PENDING", "DECIDED"})
            if rows:
                exception_ids.add(rows[0].id)
            if trigger.payload.exception_id:
                exception_ids.add(trigger.payload.exception_id)
        exceptions = tuple(exception_detail(store, exception_id=x, actor=actor, policy_path=policy_path)
                           for x in sorted(exception_ids))
        choices = tuple(choice for x in exceptions
            if (choice := store.operator_decision_for_exception(x.id)) is not None)
        for job in jobs:
            boundary.require_job(store, job.id)
            reservation = store.reservation_for_job(job.id)
            if reservation:
                reservations.append(reservation)
            payment = store.payment_for_job(job.id)
            if payment:
                payments.append(_project(v.PaymentContext, payment))
            proof_ids = {x for x in (job.latest_submission_id,
                payment.submission_id if payment else None,
                trigger.payload.submission_id if job.id == invocation.job_id else None) if x}
            proof_ids.update(x.submission_id for x in exceptions if x.job_id == job.id and x.submission_id)
            verification_ids = {x for x in (job.current_verification_id,
                payment.verification_id if payment else None) if x}
            verification_ids.update(x.verification_id for x in exceptions if x.job_id == job.id and x.verification_id)
            for record_id in verification_ids:
                record = store.get_verification(record_id)
                if record.job_id != job.id or record.issue_id != issue.id:
                    raise ValueError("verification ownership mismatch")
                proof_ids.add(record.submission_id)
                verifications[record.id] = _project(v.VerificationContext, record,
                    input_job_revision=record.job_revision,
                    total=sum(record.components.model_dump().values()),
                    applicable_to_current_job_revision=(record.id == job.current_verification_id
                        and record.result_job_revision == job.state_revision
                        and record.submission_id == job.latest_submission_id))
            for record_id in proof_ids:
                proof = store.get_submission(record_id)
                if proof.job_id != job.id or proof.issue_id != issue.id:
                    raise ValueError("proof ownership mismatch")
                submissions[proof.id] = proof
                for eid in (proof.before_evidence_id, proof.after_evidence_id):
                    boundary.evidence(store, eid)
                    evidence[eid] = _project(v.EvidenceContext, store.get_evidence(eid))
        for signal in signals:
            for eid in signal.evidence_ids:
                evidence[eid] = _project(v.EvidenceContext, store.get_evidence(eid))

        # Keyset event pagination has a fixed upper watermark and no offset drift.
        where, args = ("issue_id=? OR signal_id=?", (issue.id if issue else None, invocation.signal_id))
        all_events = [row[0] for row in store.db.execute(
            f"SELECT id FROM events WHERE {where} ORDER BY id DESC", args)]
        anchor, before = _cursor(events_cursor, 2, (max(all_events, default=0), max(all_events, default=0) + 1))
        page = [x for x in all_events if x <= anchor and x < before][:21]
        events = tuple(_event(store, x) for x in page[:20])
        recent = [_event(store, x) for x in all_events]

        # Fixed rowid watermarks exclude later inserted candidates; offset is over
        # the stable ID order, before current display facts are projected.
        smax, imax, offset = _cursor(candidates_cursor, 3, (
            store.db.execute("SELECT COALESCE(MAX(rowid),0) FROM signals").fetchone()[0],
            store.db.execute("SELECT COALESCE(MAX(rowid),0) FROM issues").fetchone()[0], 0))
        source = _signal(store, invocation.signal_id) if invocation.signal_id else signals[0] if signals else None
        candidates = []
        if source:
            for row in store.db.execute("SELECT id FROM signals WHERE rowid<=? ORDER BY id", (smax,)):
                candidate = store.get_signal(row[0])
                if candidate.id == (invocation.signal_id or source.id) or candidate.reported_location != source.reported_location:
                    continue
                boundary.signal(store, candidate.id)
                linked = store.issue_for_signal(candidate.id)
                candidates.append(v.CandidateContext(kind="signal", id=candidate.id,
                    summary=candidate.raw_text[:600], location=candidate.reported_location,
                    issue_id=linked.id if linked else None))
            for row in store.db.execute("SELECT id FROM issues WHERE rowid<=? AND location=? ORDER BY id",
                                       (imax, source.reported_location)):
                candidate = boundary._issue(store, row[0])
                candidates.append(v.CandidateContext(kind="issue", id=candidate.id,
                    summary=f"{candidate.category}: {candidate.status}", location=candidate.location,
                    state_revision=candidate.state_revision))
        latest_effect = next((e for e in recent if e.event_type in EFFECTS | {"SIMULATED_SETTLEMENT"}), None)
        latest_denial = next((e for e in recent if e.outcome == "DENIED"), None)
        inspection_error = next((e for e in recent if e.event_type in {
            "COMPLETION_INSPECTION_FAILED", "INTAKE_INSPECTION_FAILED"}), None)
        # Only effects caused by this invocation can stop this execution. An old
        # monitoring/watch result must not suppress a new independent report.
        def is_own_stop(event):
            if event.event_type not in EFFECTS:
                return False
            if event.event_type == "INVESTIGATION_ACTION_APPLIED":
                # B4's original action receipt predates invocation_id retention.
                # Its immutable decision carries the authenticated original cause.
                decision = store.get_decision(event.record_id)
                return (decision.trigger_event_id == invocation.trigger_event_id
                    and decision.decision_type in {"MONITOR", "ROUTE_EXTERNAL"})
            receipt = store.receipt_for_event(event.id)
            return receipt is not None and receipt.invocation_id == invocation.id
        own_effect = next((e for e in recent if is_own_stop(e)), None)
        stop = own_effect.event_type if own_effect else None
        if issue and issue.status in {"RESOLVED", "DUPLICATE", "INVALID"}:
            stop = issue.status
        inspections = facts.intake_inspections if facts else tuple(
            record for signal in signals for record in store.intake_inspections_for_signal(signal.id))
        effects = [e for e in recent if e.event_type in EFFECTS | {"SIMULATED_SETTLEMENT", "SETTLEMENT_DENIED"}]
        receipts = {}
        for event in effects:
            receipt = store.receipt_for_event(event.id)
            if receipt:
                receipts[receipt.id] = v.ReceiptSummary(id=receipt.id, operation=receipt.operation,
                    outcome=receipt.result.outcome, event_ids=receipt.result.event_ids,
                    record_id=getattr(receipt.result.data, "record_id", None),
                    state_revision=getattr(receipt.result.data, "state_revision", None))
        raw_service = store.get_issue(issue.id)["service_record"] if issue else None
        return v.CaseContext(invocation_id=invocation.id, invocation_revision=invocation.state_revision,
            invocation_status=invocation.status, trigger=_event(store, trigger.id), district_id=district_id,
            current_policy_version=policy["version"], issue=issue, signals=signals,
            policy=v.PolicyContext.model_validate_json(json.dumps({key: policy[key] for key in v.PolicyContext.model_fields})),
            configuration=v.ConfigurationContext(prompt_version=PROMPT_VERSION, tool_schema_version=SCHEMA_VERSION,
                text_model_id=settings.resolved_text_model_id, vision_model_id=settings.resolved_vision_model_id,
                region=settings.region),
            score=v.ScoreContext(**score.to_dict()) if score else None,
            classification=facts.classification.model_copy(update={"metadata": None}) if facts and facts.classification else None,
            jurisdiction=facts.jurisdiction.model_copy(update={"metadata": None}) if facts and facts.jurisdiction else None,
            geocode=facts.geocode if facts else None,
            unresolved_hazards=facts.unresolved_hazards if facts else (), hazard_sources=facts.hazard_sources if facts else (),
            inspections=tuple(_project(v.InspectionContext, x) for x in inspections),
            service_lookups=tuple(store.service_lookups_for_issue(issue.id)) if issue else (),
            applied_service_record=v.ServiceStatusContext.model_validate_json(json.dumps(raw_service)) if raw_service else None,
            plans=plans, jobs=jobs, vendors=tuple(store.get_vendor(x) for x in sorted({j.vendor_id for j in jobs})),
            reservations=tuple(reservations), submissions=tuple(submissions.values()), evidence=tuple(evidence.values()),
            proof_events=tuple(_event(store, store.proof_event_for_submission(x).id) for x in submissions),
            verifications=tuple(verifications.values()), exceptions=exceptions, operator_choices=choices,
            payments=tuple(payments), budget=store.budget_availability(district_id) if store.db.execute(
                "SELECT 1 FROM budgets WHERE id=?", (district_id,)).fetchone() else None,
            candidates=tuple(candidates[offset:offset+10]), events=events,
            next_candidates_cursor=f"{smax}.{imax}.{offset+10}" if len(candidates) > offset+10 else None,
            next_events_cursor=f"{anchor}.{page[19]}" if len(page) > 20 else None,
            latest_effect=latest_effect, latest_denial=latest_denial,
            effect_receipts=tuple(receipts.values()),
            latest_inspection_error=inspection_error, saved_stop=stop)
