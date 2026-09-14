"""Safe, bounded projections for human/API consumers; no mutation policy lives here."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

from . import contracts as c
from .actors import AccessError, Action
from .http_contracts import (
    BoardCounts,
    BoardMarker,
    BoardView,
    CrewJobCard,
    CrewJobListView,
    DecisionSummary,
    EvidenceDetailView,
    IssueCurrentView,
    IssueDetailView,
    IssueEvidenceView,
    IssueFactsView,
    IssueTimelineView,
    JobSummary,
    PageInfo,
    PaymentSummary,
    PlanSummary,
    ProofHistoryItem,
    ProofHistoryPage,
    ServiceLookupPage,
    ServiceLookupSummary,
    SourcePage,
    SourceSummary,
    TimelineEntityIds,
    TimelineEvent,
)
from .models import ServiceRecord
from .operations import exception_detail

_MAX_CURSOR_BYTES = 4096
_MAX_SQLITE_INT = 2 ** 63 - 1


def _cursor(kind: str, after: int, watermark: int, *, members: tuple[int, ...] | None = None) -> str:
    payload: dict[str, object] = {"k": kind, "a": after, "w": watermark}
    if members is not None:
        payload["m"] = members
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decoded_cursor(value: str | None, kind: str) -> dict[str, object] | None:
    if value in (None, "", "0"):
        return None
    try:
        if not isinstance(value, str) or len(value) > _MAX_CURSOR_BYTES:
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if len(raw) > _MAX_CURSOR_BYTES:
            raise ValueError
        decoded = json.loads(raw)
        if not isinstance(decoded, dict) or decoded.get("k") != kind:
            raise ValueError
        return decoded
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid cursor") from error


def parse_cursor(value: str | None, kind: str) -> tuple[int, int | None]:
    decoded = _decoded_cursor(value, kind)
    if decoded is None:
        return 0, None
    after, watermark = decoded.get("a"), decoded.get("w")
    if (type(after) is not int or not 0 <= after <= _MAX_SQLITE_INT
            or type(watermark) is not int or not 0 <= watermark <= _MAX_SQLITE_INT):
        raise ValueError("invalid cursor")
    return after, watermark


def _exception_cursor(value: str | None, statuses: tuple[str, ...]) -> tuple[int, int | None, int | None]:
    decoded = _decoded_cursor(value, "exceptions")
    if decoded is None:
        return 0, None, None
    after, event_watermark, row_watermark, saved_statuses = decoded.get("a"), decoded.get("e"), decoded.get("w"), decoded.get("s")
    if (type(after) is not int or type(event_watermark) is not int or type(row_watermark) is not int
            or not 0 <= after <= _MAX_SQLITE_INT or not 0 <= event_watermark <= _MAX_SQLITE_INT
            or not 0 <= row_watermark <= _MAX_SQLITE_INT or saved_statuses != list(statuses)):
        raise ValueError("invalid cursor")
    return after, event_watermark, row_watermark


def _limit(value: int, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("invalid limit")
    return value


def _page(kind: str, rows: list[tuple[int, object]], watermark: int, limit: int) -> PageInfo:
    return PageInfo(next_cursor=_cursor(kind, rows[limit - 1][0], watermark) if len(rows) > limit else None,
                    truncated=len(rows) > limit)


def _plan(store, plan: c.PlanRecord | None) -> PlanSummary | None:
    if plan is None:
        return None
    return PlanSummary(id=plan.id, primary_target=plan.primary_target, scope=plan.scope, work_area=plan.work_area,
        required_equipment=plan.required_equipment, quote_cents=plan.quote_cents,
        policy_version=plan.policy_version, dispatch_location=plan.dispatch_location)


def _job(store, job: c.JobRecord | None) -> JobSummary | None:
    if job is None:
        return None
    vendor = store.get_vendor(job.vendor_id)
    reservation = store.reservation_for_job(job.id)
    payment = store.payment_for_job(job.id)
    return JobSummary(id=job.id, vendor_id=vendor.id, vendor_label=vendor.name, status=job.status,
        state_revision=job.state_revision, quote_cents=job.price_cents,
        latest_submission_id=job.latest_submission_id, reservation_id=reservation.id if reservation else None,
        payment_id=payment.id if payment else None, simulated=job.simulated)


def _payment(store, job: c.JobRecord | None) -> PaymentSummary | None:
    if job is None:
        return None
    payment = store.payment_for_job(job.id)
    return PaymentSummary(id=payment.id, job_id=payment.job_id, submission_id=payment.submission_id,
        verification_id=payment.verification_id, amount_cents=payment.amount_cents,
        simulated=payment.simulated) if payment else None


def _source_page(store, issue_id: str, *, after: int, watermark: int | None, limit: int) -> SourcePage:
    rows, bound = store.source_rows_for_issue(issue_id, after_event_id=after, watermark=watermark, limit=limit + 1)
    items = []
    for _event_id, signal in rows[:limit]:
        items.append(SourceSummary(id=signal.id, source_role=signal.effective_source_role,
            provenance=signal.provenance, observed_at=signal.observed_at, received_at=signal.received_at,
            reported_location=signal.reported_location,
            evidence_ids=tuple(e.id for e in store.evidence_for_entity(signal_id=signal.id))))
    page = _page("sources", [(event_id, signal) for event_id, signal in rows], bound, limit)
    return SourcePage(items=tuple(items), next_cursor=page.next_cursor, truncated=page.truncated)


def _service_page(store, issue_id: str, *, after: int, watermark: int | None, limit: int) -> ServiceLookupPage:
    rows, bound = store.service_lookup_rows_for_issue(
        issue_id, after_rowid=after, watermark=watermark, limit=limit + 1,
    )
    items = tuple(ServiceLookupSummary(id=record.id, signal_id=record.signal_id, outcome=record.outcome,
        status=record.status, completed_at=record.completed_at, looked_up_at=record.looked_up_at,
        source_mode=record.source_mode, provenance=record.provenance, error_code=record.error_code)
        for _index, record in rows[:limit])
    page = _page("service", rows, bound, limit)
    return ServiceLookupPage(items=items, next_cursor=page.next_cursor, truncated=page.truncated)


def _proof_history(store, issue_id: str, *, after: int, watermark: int | None, limit: int) -> ProofHistoryPage:
    rows, bound = store.submission_rows_for_issue(issue_id, after_rowid=after, watermark=watermark, limit=limit + 1)
    issue = store.get_issue_record(issue_id)
    items = []
    for _row, submission in rows[:limit]:
        verification = store.verification_for_submission(submission.id)
        payment = store.payment_for_job(submission.job_id)
        accepted = issue.accepted_submission_id == submission.id or (payment is not None and payment.submission_id == submission.id)
        items.append(ProofHistoryItem(submission_id=submission.id, job_id=submission.job_id,
            verification_id=verification.id if verification else None, submitted_at=submission.submitted_at,
            before_evidence_id=submission.before_evidence_id, after_evidence_id=submission.after_evidence_id,
            findings=verification.findings if verification else None,
            components=verification.components if verification else None,
            total=sum(verification.components.model_dump().values()) if verification else None,
            prerequisites=verification.prerequisites if verification else (),
            unmet=verification.unmet if verification else (), accepted=accepted))
    page = _page("proof-history", rows, bound, limit)
    return ProofHistoryPage(items=tuple(items), next_cursor=page.next_cursor, truncated=page.truncated)


def issue_detail(store, boundary, issue_id: str, *, sources_cursor: str | None = None,
                 sources_limit: int = 20, service_cursor: str | None = None,
                 service_limit: int = 20, proof_cursor: str | None = None,
                 proof_limit: int = 20, policy_path=None) -> IssueDetailView:
    issue = boundary.issue(store, issue_id)
    sources_after, sources_watermark = parse_cursor(sources_cursor, "sources")
    service_after, service_watermark = parse_cursor(service_cursor, "service")
    proof_after, proof_watermark = parse_cursor(proof_cursor, "proof-history")
    source_page = _source_page(store, issue_id, after=sources_after, watermark=sources_watermark,
                               limit=_limit(sources_limit, 50))
    service_page = _service_page(store, issue_id, after=service_after, watermark=service_watermark,
                                 limit=_limit(service_limit, 50))
    history = _proof_history(store, issue_id, after=proof_after, watermark=proof_watermark,
                             limit=_limit(proof_limit, 50))
    facts = store.current_issue_facts(issue_id)
    plans = store.plans_for_issue(issue_id)
    jobs = store.jobs_for_issue(issue_id)
    plan = plans[-1] if plans else None
    job = jobs[-1] if jobs else None
    exceptions = store.exceptions_for_issue(issue_id)
    latest_exception = next((item for item in exceptions if item.status in {"PENDING", "DECIDED"}), None)
    detail = exception_detail(store, exception_id=latest_exception.id, actor=boundary.actor,
                               policy_path=policy_path) if latest_exception is not None else None
    submission = store.get_submission(job.latest_submission_id) if job and job.latest_submission_id else None
    verification_id = job.current_verification_id if job and job.current_verification_id else None
    accepted_submission_id = store.get_issue_record(issue_id).accepted_submission_id
    accepted_verification = store.verification_for_submission(accepted_submission_id) if accepted_submission_id else None
    accepted_verification_id = accepted_verification.id if accepted_verification else None
    inspections = facts.intake_inspections
    decisions = store.decisions_for_issue(issue_id)
    latest = decisions[-1] if decisions else None
    decision = None
    if latest is not None:
        trigger = store.get_event(latest.trigger_event_id)
        decision = DecisionSummary(id=latest.id, decision_type=latest.decision_type, summary=latest.summary,
            actor_label=trigger.actor.label, actor_type=trigger.actor.actor_type, next_actor=latest.next_actor,
            next_event=latest.next_event, created_at=latest.created_at, evidence_ids=latest.evidence_ids,
            event_id=trigger.id)
    service_record_json = store.get_issue(issue_id)["service_record"]
    service_record = ServiceRecord.from_dict(service_record_json) if service_record_json is not None else None
    official = service_record.id if service_record is not None else None
    allowed = detail.allowed_next if detail is not None else ()
    next_actor = "operator" if detail is not None and "request_completion" in allowed else None
    if detail is None and job is not None:
        crew_action = {
            "POSTED": "accept_job",
            "ASSIGNED": "check_in",
            "CHECKED_IN": "submit_proof",
            "REWORK_REQUIRED": "submit_proof",
        }.get(job.status)
        if crew_action is not None:
            next_actor, allowed = "crew", (crew_action,)
    return IssueDetailView(issue=issue,
        current=IssueCurrentView(next_actor=next_actor, allowed_next=allowed, plan=_plan(store, plan),
            job=_job(store, job), exception=detail, payment=_payment(store, job)),
        sources=source_page, service_records=service_page,
        facts=IssueFactsView(classification=facts.classification, jurisdiction=facts.jurisdiction,
            geocode=facts.geocode, official_conflict_record_id=official,
            official_record_status=service_record.status if service_record else None,
            official_conflict_state=service_record.conflict if service_record else None,
            official_completed_at=service_record.completed_at if service_record else None),
        evidence=IssueEvidenceView(original_before_evidence_id=submission.before_evidence_id if submission else None,
            current_after_evidence_id=submission.after_evidence_id if submission else None,
            latest_submission_id=submission.id if submission else None, verification_id=verification_id,
            inspection_id=inspections[-1].id if inspections else None, history=history,
            accepted_submission_id=accepted_submission_id,
            accepted_verification_id=accepted_verification_id,
            resolved_at=store.get_issue_record(issue_id).resolved_at), latest_decision=decision,
        timeline_url=f"/api/issues/{issue_id}/events")


def issue_timeline(store, boundary, issue_id: str, *, cursor: str | None = None,
                   limit: int = 20) -> IssueTimelineView:
    boundary.issue(store, issue_id)
    before, watermark = parse_cursor(cursor, "events")
    limit = _limit(limit, 50)
    if watermark is None:
        watermark = store.db.execute("SELECT COALESCE(MAX(id),0) FROM events WHERE issue_id=?", (issue_id,)).fetchone()[0]
    upper = min(watermark, before - 1) if before else watermark
    # Read only registered columns plus the fixed EventFacts shape.  Foundation's
    # immutable SIGNAL_LINKED producer predates typed actor columns, so get_event()
    # cannot serialize it.  Keeping this compatibility handling here makes the
    # public projection complete without exposing its raw payload.
    rows = store.db.execute(
        "SELECT id,signal_id,job_id,event_type,timestamp,payload,actor_json FROM events "
        "WHERE issue_id=? AND id<=? ORDER BY id DESC LIMIT ?", (issue_id, upper, limit + 1)
    ).fetchall()
    events = []
    for event in rows[:limit]:
        payload = json.loads(event[5])
        actor = json.loads(event[6]) if event[6] else None
        actor_label = actor.get("label", "Foundation service") if actor else "Foundation service"
        actor_type = actor.get("actor_type", "service") if actor else "service"
        settlement = payload.get("settlement") if isinstance(payload.get("settlement"), dict) else None
        payment_id = settlement.get("payment_id") if settlement else None
        score = None
        components = None
        # SIGNAL_LINKED is the sole legacy producer that persists a full evidence
        # score under payload.score.  Project only its fixed, validated shape; the
        # rest of the payload remains private and unavailable to API consumers.
        if event[3] == "SIGNAL_LINKED":
            try:
                candidate = payload.get("score")
                if (isinstance(candidate, dict) and set(candidate) == {"total", "components", "threshold", "actionable"}
                        and type(candidate["total"]) is int and 0 <= candidate["total"] <= 100
                        and type(candidate["threshold"]) is int and type(candidate["actionable"]) is bool):
                    components = c.EvidenceComponents.model_validate(candidate["components"])
                    score = candidate["total"]
            except (TypeError, ValueError):
                pass
        events.append(TimelineEvent(id=event[0], occurred_at=datetime.fromisoformat(event[4]), type=event[3],
            actor_label=actor_label, actor_type=actor_type, outcome=payload.get("outcome"),
            reason_code=payload.get("reason_code"), summary=payload.get("summary"),
            entity_ids=TimelineEntityIds(signal_id=event[1] or payload.get("signal_id"), job_id=event[2],
                submission_id=payload.get("submission_id"), exception_id=payload.get("exception_id"),
                decision_id=payload.get("decision_id"), payment_id=payment_id),
            # Foundation's legacy SIGNAL_LINKED payload calls signal IDs
            # `evidence_ids`; they are not evidence records and cannot be exposed
            # as evidence links. Typed event payloads retain their real IDs.
            evidence_ids=() if event[3] == "SIGNAL_LINKED" else tuple(payload.get("evidence_ids", ())),
            provenance=payload.get("provenance"), simulated=payload.get("simulated"),
            evidence_score=score, evidence_components=components))
    page = _page("events", [(event[0], event) for event in rows], watermark, limit)
    return IssueTimelineView(issue_id=issue_id, events=tuple(events), next_cursor=page.next_cursor,
                             truncated=page.truncated)


def board(store, boundary, district_id: str, *, cursor: str | None = None, limit: int = 20) -> BoardView:
    boundary.require_district()
    after, watermark = parse_cursor(cursor, "board")
    rows, bound = store.issue_rows(after_rowid=after, watermark=watermark, limit=_limit(limit, 100) + 1)
    by_status = {row[0]: row[1] for row in store.db.execute(
        "SELECT status,COUNT(*) FROM issues WHERE rowid<=? GROUP BY status", (bound,))}
    # Board membership is keyed by issue rowid; exception rowids are a different table/key space.
    attention = store.db.execute("SELECT COUNT(DISTINCT issue_id) FROM exceptions "
        "WHERE status IN ('PENDING','DECIDED')").fetchone()[0]
    counts = BoardCounts(watching=by_status.get("CANDIDATE", 0), active=by_status.get("RESOLUTION_ACTIVE", 0),
        resolved=by_status.get("RESOLVED", 0), attention=attention)
    markers = []
    for _row, issue_id in rows[:limit]:
        issue = boundary._issue(store, issue_id)
        facts = store.current_issue_facts(issue_id)
        jobs = store.jobs_for_issue(issue_id)
        job = jobs[-1] if jobs else None
        exception = store.open_completion_exception(job.id) if job else None
        if issue.status == "RESOLVED":
            marker_state = "resolved"
        elif exception is not None:
            marker_state = "attention"
        elif issue.status == "RESOLUTION_ACTIVE":
            marker_state = "active"
        else:
            marker_state = "watching"
        location = facts.geocode.location if facts.geocode and facts.geocode.outcome == "MATCH" else None
        payment = store.payment_for_job(job.id) if job else None
        markers.append(BoardMarker(issue_id=issue.id, status=issue.status, marker_state=marker_state,
            latitude=location.lat if location else None, longitude=location.lon if location else None,
            accuracy_m=location.accuracy_m if location else None,
            location_provenance=location.provenance if location else None,
            location_unknown_reason=None if location else (facts.geocode.outcome if facts.geocode else "unknown"),
            label=issue.location, current_job_id=job.id if job else None, payment_id=payment.id if payment else None,
            simulated=job.simulated if job else None))
    page = _page("board", [(rowid, issue_id) for rowid, issue_id in rows], bound, limit)
    budget = store.budget_availability(district_id)
    return BoardView(as_of=datetime.now(UTC), district_id=district_id, policy_version=store.get_budget(district_id).policy_version,
        counts=counts, budget=budget, markers=tuple(markers), next_cursor=page.next_cursor, truncated=page.truncated)


def exception_inbox(store, boundary, *, cursor: str | None = None, limit: int = 20,
                    status: str | None = None, policy_path=None):
    boundary.require(Action.READ_ISSUE)
    statuses = (status,) if status is not None else ("PENDING", "DECIDED")
    if any(item not in {"PENDING", "DECIDED", "HANDLED", "CANCELLED"} for item in statuses):
        raise ValueError("invalid status")
    after, event_watermark, row_watermark = _exception_cursor(cursor, statuses)
    rows, event_watermark, row_watermark, counts = store.exception_snapshot_rows(
        after_rowid=after, limit=_limit(limit, 50) + 1, event_watermark=event_watermark,
        row_watermark=row_watermark, statuses=statuses,
    )
    rows = [(rowid, record) for rowid, record in rows if _authorized_exception_row(store, boundary, record.id)]
    details = []
    for _row, exception in rows[:limit]:
        boundary._issue(store, exception.issue_id)
        details.append(exception_detail(store, exception_id=exception.id, actor=boundary.actor, policy_path=policy_path))
    has_next = len(rows) > limit
    page = PageInfo(next_cursor=_exception_page_cursor(rows[limit - 1][0], event_watermark, row_watermark, statuses)
                    if has_next else None, truncated=has_next)
    from .http_contracts import ExceptionListPage
    return ExceptionListPage(exceptions=tuple(details), pending_count=counts.get("PENDING", 0),
        decided_count=counts.get("DECIDED", 0), next_cursor=page.next_cursor,
        truncated=page.truncated)


def _authorized_exception_row(store, boundary, exception_id: str) -> bool:
    try:
        boundary._issue(store, store.get_exception(exception_id).issue_id)
    except AccessError:
        return False
    return True


def _exception_page_cursor(after: int, event_watermark: int, row_watermark: int, statuses: tuple[str, ...]) -> str:
    raw = json.dumps({"a": after, "e": event_watermark, "k": "exceptions", "s": list(statuses), "w": row_watermark},
                     separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def crew_jobs(store, boundary, *, cursor: str | None = None, limit: int = 20) -> CrewJobListView:
    boundary.require(Action.READ_JOB)
    after, watermark = parse_cursor(cursor, "crew-jobs")
    vendor_id = boundary.actor.vendor_id if boundary.actor.actor_type == "crew" else None
    rows, bound = store.job_rows_for_vendor(vendor_id, after_rowid=after, watermark=watermark,
                                             limit=_limit(limit, 50) + 1)
    cards = []
    for _row, job in rows[:limit]:
        view = boundary.job(store, job.id)
        pending = store.open_completion_exception(job.id)
        cards.append(CrewJobCard(id=view.id, issue_id=view.issue_id, status=view.status,
            state_revision=view.state_revision, location=view.location, scope=view.scope,
            price_cents=view.price_cents, simulated=view.simulated,
            latest_submission_id=view.latest_submission_id,
            pending_exception_status=pending.status if pending else None, created_at=job.created_at))
    page = _page("crew-jobs", rows, bound, limit)
    return CrewJobListView(jobs=tuple(cards), next_cursor=page.next_cursor, truncated=page.truncated)


def evidence_detail(store, boundary, evidence_id: str, *, job_id: str | None = None) -> EvidenceDetailView:
    if boundary.actor.actor_type == "resident":
        base = boundary.receipt_evidence(store, evidence_id)
    else:
        base = boundary.evidence(store, evidence_id, job_id=job_id)
    links = store.evidence_associations(evidence_id)
    link = next((item for item in links if item.issue_id is not None), links[0])
    role = "intake" if link.role == "signal" else "before" if link.role == "before" else "after"
    submission_id = None
    if link.job_id:
        for record in store.db.execute("SELECT id FROM submissions WHERE job_id=? AND (before_evidence_id=? OR after_evidence_id=?)",
                                       (link.job_id, evidence_id, evidence_id)):
            submission_id = record[0]
            break
    inspection = next((record for record in store.intake_inspections_for_signal(link.signal_id)
                       if record.evidence_id == evidence_id), None) if link.signal_id else None
    return EvidenceDetailView(**base.model_dump(), role=role, issue_id=link.issue_id,
        job_id=link.job_id, submission_id=submission_id, inspection_status=inspection.outcome if inspection else None)
