"""Immutable operational-intent recording; this module never performs the proposed action."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from . import contracts as c
from .actors import AccessBoundary, Action
from .http_contracts import OperationalDecisionProposalRequest
from .investigation import _validated_cause, stable_id
from .operations import (
    _completion_denial,
    _configured_budget,
    _current_budget_shortage,
    _current_completion,
    _dispatch_evaluation,
    _exception_current,
    _financial_reservation,
    _operator_decision_cause,
    _paid_contract,
    _pre_job_escalation_gate,
    _reserved_contract,
    _saved_budget_shortage,
    _saved_completion_denial,
    _settlement_action_gate,
)
from .policy import load_policy
from .store import RevisionConflict, Store, request_fingerprint


def _expected_subject(proposal: OperationalDecisionProposalRequest) -> int:
    job_revision = getattr(proposal.basis, "expected_job_revision", None)
    return job_revision if job_revision is not None else proposal.basis.expected_issue_revision


def _job_id(basis: c.OperationalDecisionProposalBasis) -> str | None:
    return getattr(basis, "job_id", None)


def _structural(store: Store, *, issue_id: str, proposal: OperationalDecisionProposalRequest,
                context: c.MutationContext, policy: dict) -> dict:
    """Validate immutable relationships, deliberately excluding current eligibility."""
    if context.operation != Action.DECIDE_OPERATIONAL.value or context.expected_revision is None:
        raise ValueError("operational decision requires its service operation and revision")
    if context.expected_revision != _expected_subject(proposal):
        raise ValueError("proposal revision does not match request header")
    boundary = AccessBoundary(context.actor, policy["district"])
    boundary.require(Action.DECIDE_OPERATIONAL)
    issue = boundary.issue(store, issue_id)
    basis = proposal.basis
    job = submission = verification = plan = vendor = payment = exception = operator_choice = denial = None
    if basis.kind == "dispatch":
        plan = store.get_plan(basis.plan_id)
        vendor = store.get_vendor(basis.vendor_id)
        if plan.issue_id != issue_id:
            raise ValueError("dispatch plan does not belong to issue")
    elif basis.kind in {"settlement", "completion_operator", "resolve"}:
        job = boundary.require_job(store, basis.job_id)
        if job.issue_id != issue_id:
            raise ValueError("job does not belong to issue")
        submission = store.get_submission(basis.submission_id)
        verification = store.get_verification(basis.verification_id)
        if (submission.job_id != job.id or submission.issue_id != issue_id or verification.job_id != job.id
                or verification.issue_id != issue_id or verification.submission_id != submission.id):
            raise ValueError("proof or verification does not belong to job")
        plan = store.get_plan(job.plan_id)
        if basis.kind == "completion_operator":
            denial = _saved_completion_denial(store, job=job, submission=submission,
                verification=verification, denial_event_id=basis.denial_event_id, policy=policy)
        if basis.kind == "resolve":
            payment = store.get_payment(basis.payment_id)
            if (payment.job_id != job.id or payment.issue_id != issue_id
                    or payment.submission_id != submission.id or payment.verification_id != verification.id):
                raise ValueError("payment does not belong to paid proof")
    elif basis.kind == "rework":
        operator_choice = store.get_operator_decision(basis.operator_decision_id)
        job = boundary.require_job(store, operator_choice.job_id)
        exception = store.get_exception(operator_choice.exception_id)
        submission = store.get_submission(operator_choice.submission_id)
        if (job.issue_id != issue_id or exception.issue_id != issue_id or exception.job_id != job.id
                or submission.job_id != job.id):
            raise ValueError("operator choice does not belong to issue")
        _operator_decision_cause(store, operator_choice, context)
        plan = store.get_plan(job.plan_id)
    elif basis.kind == "budget":
        denial, plan = _saved_budget_shortage(store, issue=issue,
            denial_event_id=basis.denial_event_id, policy=policy)
        audit = denial.payload.dispatch
        vendor = store.get_vendor(audit.vendor_id)
    elif basis.kind == "no_vendor":
        plans = store.plans_for_issue(issue_id)
        plan = plans[-1] if plans else None
    # The saved cause is authorization, not a model argument. Direct service calls remain absent.
    cause = _validated_cause(store, context, issue_id=issue_id, signal_id=None,
                             job_id=job.id if job else None,
                             submission_id=submission.id if submission else None)
    for evidence_id in proposal.evidence_ids:
        boundary.issue_evidence(store, issue_id, evidence_id)
    return {"issue": issue, "job": job, "submission": submission, "verification": verification,
            "plan": plan, "vendor": vendor, "payment": payment, "exception": exception,
            "operator_choice": operator_choice, "denial": denial, "cause": cause}


def _evaluation(store: Store, *, proposal: OperationalDecisionProposalRequest, resolved: dict,
                context: c.MutationContext, policy: dict) -> tuple[c.GateRecord, c.EvidenceComponents | c.VerificationComponents, str, str]:
    """Purely read current policy facts; no event, receipt, money, or state mutation."""
    basis, issue, job = proposal.basis, resolved["issue"], resolved["job"]
    if basis.kind == "dispatch":
        plan, vendor = resolved["plan"], resolved["vendor"]
        _facts, _quote, _budget, score, unmet = _dispatch_evaluation(store, plan=plan, issue=issue,
            vendor_id=vendor.id, expected_revision=basis.expected_issue_revision, policy=policy)
        gate = c.GateRecord(name="dispatch", allowed=not unmet, unmet=unmet)
        return gate, c.EvidenceComponents(**score.components), "service", "dispatch_vendor"
    if basis.kind == "settlement":
        submission, verification, plan = resolved["submission"], resolved["verification"], resolved["plan"]
        unmet: list[str] = []
        if basis.expected_job_revision != job.state_revision:
            unmet.append("stale_job_revision")
        if submission.id != job.latest_submission_id:
            unmet.append("not_latest_proof")
        if issue.status != "RESOLUTION_ACTIVE":
            unmet.append("issue_not_active")
        if job.status in {"CANCELLED", "REJECTED"}:
            unmet.append("job_terminal")
        if plan.policy_version != policy["version"]:
            unmet.append("policy_changed")
        if store.open_completion_exception(job.id) is not None:
            unmet.append("completion_exception_pending")
        if job.latest_submission_id != submission.id or job.current_verification_id != verification.id:
            unmet.append("current_verification_required")
        payment = store.payment_for_job(job.id)
        if payment is None and job.status not in {"PAID", "CANCELLED", "REJECTED"} and "policy_changed" not in unmet:
            _reserved_contract(store, job, plan, policy)
        if not unmet and payment is None:
            _financial_reservation(store, job)
            try:
                _current_completion(store, job=job, submission=submission, verification=verification, policy=policy)
            except RevisionConflict:
                unmet.append("stale_completion_basis")
        gate = _settlement_action_gate(policy, job, verification,
            already_paid=payment is not None, unmet=tuple(unmet))
        return gate, verification.components, "service", "release_payment"
    if basis.kind == "completion_operator":
        verification, submission = resolved["verification"], resolved["submission"]
        unmet: list[str] = []
        if basis.expected_job_revision != job.state_revision:
            unmet.append("stale_job_revision")
        if (job.status not in {"PROOF_SUBMITTED", "VERIFIED"}
                or issue.status != "RESOLUTION_ACTIVE" or job.latest_submission_id != submission.id
                or job.current_verification_id != verification.id
                or verification.result_job_revision != job.state_revision):
            unmet.append("stale_completion_basis")
        else:
            try:
                _completion_denial(store, job=job, submission=submission, verification=verification,
                                   denial_event_id=basis.denial_event_id, policy=policy)
            except RevisionConflict:
                unmet.append("stale_completion_basis")
        if all(gate.allowed for gate in verification.prerequisites):
            unmet.append("completion_denial_not_required")
        return c.GateRecord(name="operator_escalation", allowed=not unmet, unmet=tuple(unmet)), verification.components, "operator", "escalate_to_operator"
    if basis.kind in {"authority", "no_vendor", "budget"}:
        plan, current_gate = _pre_job_escalation_gate(store, issue=issue, kind=basis.kind, policy=policy)
        unmet = list(current_gate.unmet)
        if basis.expected_issue_revision != issue.state_revision:
            unmet.append("stale_issue_revision")
        if basis.kind == "budget":
            _configured_budget(store, policy)
            if resolved["denial"].state_revision != issue.state_revision:
                unmet.append("budget_shortage_not_current")
            else:
                try:
                    _current_budget_shortage(store, issue=issue, denial_event_id=basis.denial_event_id,
                                             policy=policy)
                except RevisionConflict:
                    unmet.append("budget_shortage_not_current")
        return c.GateRecord(name="operator_escalation", allowed=not unmet, unmet=tuple(unmet)), issue.components, "operator", "escalate_to_operator"
    if basis.kind == "rework":
        choice, exception = resolved["operator_choice"], resolved["exception"]
        unmet = []
        if basis.expected_job_revision != job.state_revision:
            unmet.append("stale_job_revision")
        if choice.handled_at is not None or exception.status != "DECIDED":
            unmet.append("operator_choice_not_actionable")
        try:
            _exception_current(store, exception, policy)
        except RevisionConflict:
            unmet.append("stale_completion_basis")
        verification = store.get_verification(exception.verification_id) if exception.verification_id else None
        components = verification.components if verification else issue.components
        return c.GateRecord(name="rework", allowed=not unmet, unmet=tuple(unmet)), components, "service", "request_rework"
    # resolve
    verification = resolved["verification"]
    unmet = []
    if basis.expected_issue_revision != issue.state_revision:
        unmet.append("stale_issue_revision")
    paid, _reservation, _plan, paid_verification = _paid_contract(store, job)
    if paid.id != resolved["payment"].id or paid_verification.id != verification.id:
        raise ValueError("paid contract does not match proposed closure")
    if store.open_completion_exception(job.id) is not None:
        unmet.append("completion_exception_pending")
    if issue.status not in {"RESOLUTION_ACTIVE", "RESOLVED"}:
        unmet.append("issue_not_active")
    return c.GateRecord(name="closure", allowed=not unmet, unmet=tuple(unmet)), verification.components, "service", "close_issue"


def _snapshot(proposal: OperationalDecisionProposalRequest, resolved: dict) -> c.OperationalDecisionBasis:
    issue, job, basis = resolved["issue"], resolved["job"], proposal.basis
    return c.OperationalDecisionBasis(proposal=basis, actual_issue_revision=issue.state_revision,
        actual_job_revision=job.state_revision if job else None, plan_id=resolved["plan"].id if resolved["plan"] else None,
        vendor_id=resolved["vendor"].id if resolved["vendor"] else None, job_id=job.id if job else None,
        submission_id=resolved["submission"].id if resolved["submission"] else None,
        verification_id=resolved["verification"].id if resolved["verification"] else None,
        exception_id=resolved["exception"].id if resolved["exception"] else None,
        operator_decision_id=resolved["operator_choice"].id if resolved["operator_choice"] else None,
        payment_id=resolved["payment"].id if resolved["payment"] else None,
        denial_event_id=resolved["denial"].id if resolved["denial"] else None)


def record_operational_decision(store: Store, *, issue_id: str, proposal: OperationalDecisionProposalRequest,
                                context: c.MutationContext) -> c.RequestReceipt:
    policy = load_policy()
    # Structural actor/cause/reference checks intentionally precede replay, but not current gates.
    _structural(store, issue_id=issue_id, proposal=proposal, context=context, policy=policy)
    fingerprint = request_fingerprint({"issue_id": issue_id, "proposal": proposal.model_dump(mode="json"),
        "actor": context.actor.model_dump(mode="json"), "invocation_id": context.invocation_id,
        "expected_revision": context.expected_revision})
    with store.transaction() as tx:
        resolved = _structural(store, issue_id=issue_id, proposal=proposal, context=context, policy=policy)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            return previous
        gate, components, next_actor, next_event = _evaluation(store, proposal=proposal, resolved=resolved,
                                                                 context=context, policy=policy)
        issue, job, cause = resolved["issue"], resolved["job"], resolved["cause"]
        if cause is None:
            cause = tx.append_event(c.NewEvent(issue_id=issue.id, job_id=job.id if job else None,
                event_type="OPERATIONAL_DECISION_REQUESTED", timestamp=datetime.now(UTC), actor=context.actor,
                state_revision=job.state_revision if job else issue.state_revision, policy_version=policy["version"],
                payload=c.EventFacts(summary="Direct service operational decision request", outcome="OK")))
        snapshot = _snapshot(proposal, resolved)
        decision = c.DecisionRecord(id=stable_id("operational-decision", issue.id, context.actor.actor_id,
            context.operation, context.idempotency_key), issue_id=issue.id, job_id=job.id if job else None,
            trigger_event_id=cause.id, invocation_id=context.invocation_id, decision_type=proposal.decision_type,
            summary=proposal.summary, evidence_ids=proposal.evidence_ids, score_components=components,
            policy_version=policy["version"], gate_results=(gate,), next_actor=next_actor,
            next_event=next_event, basis=snapshot, created_at=datetime.now(UTC))
        tx.append_decision(decision)
        event = tx.append_event(c.NewEvent(issue_id=issue.id, job_id=job.id if job else None,
            invocation_id=context.invocation_id, event_type="OPERATIONAL_DECISION_SAVED", timestamp=datetime.now(UTC),
            actor=context.actor, state_revision=job.state_revision if job else issue.state_revision,
            policy_version=policy["version"], payload=c.EventFacts(summary=proposal.summary, outcome="OK",
                record_id=decision.id, decision_id=decision.id, evidence_ids=proposal.evidence_ids,
                score_components=components, gate_results=(gate,))))
        result = c.ToolResult[c.OperationalDecisionResult](outcome="OK", reason_code="DECISION_SAVED",
            data=c.OperationalDecisionResult(record_id=decision.id,
                state_revision=job.state_revision if job else issue.state_revision, decision=decision),
            unmet=gate.unmet, evidence_ids=proposal.evidence_ids, event_ids=(event.id,))
        receipt = c.RequestReceipt(id=str(uuid4()), operation=context.operation, actor_id=context.actor.actor_id,
            idempotency_key=context.idempotency_key, request_sha256=fingerprint, issue_id=issue.id,
            job_id=job.id if job else None, invocation_id=context.invocation_id,
            created_at=datetime.now(UTC), result=result)
        tx.save_request(receipt)
        return receipt
