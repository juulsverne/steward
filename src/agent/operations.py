"""Policy-owning B5 operations. No model, adapter, crew action or payment runs here."""
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from . import contracts as c
from .actors import AccessBoundary, Action
from .investigation import _validated_cause
from .policy import (
    DEFAULT_POLICY_PATH,
    dispatch_gate,
    load_policy,
    quote_cents,
    rank_vendors,
    required_equipment,
    vendor_eligibility,
)
from .store import Store, request_fingerprint


class VendorOptions(c.Record):
    plan: c.PlanRecord
    issue_revision: c.Nonnegative
    vendors: tuple[c.VendorRecord, ...]


def _authorize(store, context, policy, action, issue_id):
    if context.operation != action.value:
        raise ValueError("operation does not match mutation")
    boundary = AccessBoundary(context.actor, policy["district"])
    boundary.require(action)
    boundary.issue(store, issue_id)
    _validated_cause(store, context, issue_id=issue_id, signal_id=None)
    if context.expected_revision is None:
        raise ValueError("expected issue revision is required")


def _fingerprint(context, **body):
    return request_fingerprint(body | {"actor": context.actor.model_dump(mode="json"),
        "expected_revision": context.expected_revision, "invocation_id": context.invocation_id})


def _reference(fact):
    return c.PlanFactReference(id=fact.id, fact_version=fact.fact_version,
                               source_issue_revision=fact.source_issue_revision)


def _inspection_reference(store, inspection):
    if inspection.outcome != "SUCCESS" or inspection.findings is None:
        return None
    source = store.get_intake_inspection(inspection.cached_from_id) if inspection.cached_from_id else inspection
    if (source.outcome != "SUCCESS" or not source.cache_eligible or source.cached_from_id is not None
            or source.claim_id is None or source.findings != inspection.findings
            or source.cache_key != inspection.cache_key or source.evidence_sha256 != inspection.evidence_sha256):
        return None
    claim = store.get_intake_claim(source.claim_id)
    if (claim.status != "FINISHED" or claim.cache_key != source.cache_key
            or claim.evidence_id != source.evidence_id or claim.signal_id != source.signal_id
            or claim.evidence_sha256 != source.evidence_sha256 or claim.finished_at is None
            or any(getattr(record, field) != getattr(claim.basis, field)
                   for record in (source, inspection) for field in type(claim.basis).model_fields)):
        return None
    receipt = store.request_for_operation(c.MutationContext(actor=claim.actor, operation=claim.operation,
                                                          idempotency_key=claim.idempotency_key))
    if (receipt is None or receipt.request_sha256 != claim.request_sha256
            or receipt.result.outcome != "OK" or receipt.result.data is None
            or receipt.result.data.record_id != source.id):
        return None
    # The requesting evidence and canonical signal link remain the ownership boundary;
    # the identical-byte inference source may have been produced for another signal.
    evidence = store.get_evidence(inspection.evidence_id)
    if evidence.image_sha256 != inspection.evidence_sha256 or evidence not in store.evidence_for_entity(
        signal_id=inspection.signal_id
    ):
        return None
    return c.PlanInspectionReference(inspection_id=inspection.id, source_inspection_id=source.id,
        claim_id=claim.id, signal_id=inspection.signal_id, evidence_id=evidence.id,
        evidence_sha256=evidence.image_sha256, cache_key=source.cache_key)


def _source_contract(store, facts):
    """Completeness and exact provenance only; dispatch authority is a separate gate."""
    classified, jurisdiction, geocode = facts.classification, facts.jurisdiction, facts.geocode
    unmet = []
    if classified is None:
        return ("classification_missing",), ()
    if any(value is None for value in (classified.primary_target, classified.full_cleanup_scope,
                                       classified.marked_work_area, classified.large_object_count)):
        unmet.append("scope_incomplete")
    if classified.unknowns:
        unmet.append("scope_unknowns")
    if jurisdiction is None:
        unmet.append("current_jurisdiction_missing")
    elif jurisdiction.unknowns:
        unmet.append("authority_unknowns")
    if geocode is None or geocode.location is None:
        unmet.append("current_location_missing")
    references = []
    if not classified.supporting_evidence_ids:
        unmet.append("scope_evidence_missing")
    for evidence_id in classified.supporting_evidence_ids:
        candidates = []
        for inspection in facts.intake_inspections:
            if inspection.evidence_id == evidence_id:
                reference = _inspection_reference(store, inspection)
                if reference is not None:
                    candidates.append((inspection, reference))
        if not candidates:
            unmet.append("successful_scope_inspection_missing")
            continue
        inspection, reference = max(candidates, key=lambda pair: (pair[0].created_at, pair[0].id))
        if inspection.findings.unknowns:
            unmet.append("inspection_unknowns")
        references.append(reference)
    return tuple(dict.fromkeys(unmet)), tuple(references)


def _receipt(tx, context, fingerprint, issue, event_type, *, record_id, revision,
             policy_version, unmet=(), dispatch=None, job_id=None, evidence_ids=(), score=None):
    outcome = "DENIED" if unmet else "OK"
    reason = ("STALE_ISSUE_REVISION" if "stale_issue_revision" in unmet else
              "POLICY_DENIED") if unmet else None
    event = tx.append_event(c.NewEvent(issue_id=issue.id, job_id=job_id,
        invocation_id=context.invocation_id, event_type=event_type, timestamp=datetime.now(UTC),
        actor=context.actor, state_revision=issue.state_revision, policy_version=policy_version,
        payload=c.EventFacts(outcome=outcome, reason_code=reason, record_id=record_id,
            unmet=unmet, evidence_ids=evidence_ids, dispatch=dispatch, simulated=True if job_id else None,
            score_components=c.EvidenceComponents(**score.components) if score else None,
            gate_results=(c.GateRecord(name="dispatch_policy", allowed=not unmet, unmet=unmet),)
                if dispatch else tuple(c.GateRecord(name=gate, allowed=False, unmet=(gate,)) for gate in unmet))))
    receipt = c.RequestReceipt(id=str(uuid4()), operation=context.operation, actor_id=context.actor.actor_id,
        idempotency_key=context.idempotency_key, request_sha256=fingerprint, issue_id=issue.id,
        job_id=job_id, invocation_id=context.invocation_id, created_at=datetime.now(UTC),
        result=c.ToolResult[c.EntityResult](outcome=outcome, reason_code=reason, unmet=unmet,
            data=c.EntityResult(record_id=record_id, state_revision=revision),
            evidence_ids=evidence_ids, event_ids=(event.id,)))
    tx.save_request(receipt)
    return receipt


def build_resolution_plan(store: Store, *, issue_id: str, classification_fact_id: str,
                          context: c.MutationContext,
                          policy_path: Path = DEFAULT_POLICY_PATH) -> c.RequestReceipt:
    policy = load_policy(policy_path)
    _authorize(store, context, policy, Action.BUILD_PLAN, issue_id)
    fingerprint = _fingerprint(context, issue_id=issue_id, classification_fact_id=classification_fact_id)
    with store.transaction() as tx:
        _authorize(store, context, policy, Action.BUILD_PLAN, issue_id)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            return previous
        issue = tx.require_issue(issue_id)
        facts = store.current_issue_facts(issue_id)
        unmet, inspections = _source_contract(store, facts)
        unmet = list(unmet)
        if context.expected_revision != issue.state_revision:
            unmet.append("stale_issue_revision")
        if facts.classification is None or facts.classification.id != classification_fact_id:
            unmet.append("classification_not_current")
        if issue.status not in {"CANDIDATE", "MONITORING", "ACTIONABLE"} or store.active_job_for_issue(issue_id):
            unmet.append("issue_not_plannable")
        classified = facts.classification
        if classified is not None:
            try:
                quote = quote_cents(policy, classified.category, large_objects=classified.large_object_count)
                equipment = tuple(required_equipment(policy, classified.category))
            except ValueError:
                unmet.append("service_scope_not_priceable")
        if unmet:
            return _receipt(tx, context, fingerprint, issue, "PLAN_DENIED", record_id=issue.id,
                            revision=issue.state_revision, unmet=tuple(dict.fromkeys(unmet)),
                            policy_version=policy["version"])
        origins = {classified.provenance, facts.jurisdiction.provenance, facts.geocode.provenance,
                   *(store.get_evidence(e).provenance for e in classified.supporting_evidence_ids)}
        basis = c.PlanBasis(classification=_reference(classified), jurisdiction=_reference(facts.jurisdiction),
            geocode=_reference(facts.geocode), issue_revision_before_plan=issue.state_revision,
            issue_revision_after_plan=issue.state_revision + 1, evidence_ids=classified.supporting_evidence_ids,
            inspections=inspections, provenance="synthetic" if "synthetic" in origins else
            "seeded" if "seeded" in origins else "live")
        plan = c.PlanRecord(id=str(uuid4()), issue_id=issue.id, district_id=policy["district"],
            service_type=classified.category, condition="; ".join(classified.visible_objects) or classified.primary_target,
            scope=classified.full_cleanup_scope, work_area=classified.marked_work_area,
            primary_target=classified.primary_target, dispatch_location=facts.geocode.location, basis=basis,
            required_equipment=equipment, crew_count=2, large_objects=classified.large_object_count,
            quote_cents=quote, policy_version=policy["version"], created_at=datetime.now(UTC))
        tx.insert_plan(plan)
        issue = issue.model_copy(update={"state_revision": issue.state_revision + 1})
        tx.replace_issue(issue, context.expected_revision)
        return _receipt(tx, context, fingerprint, issue, "PLAN_CREATED", record_id=plan.id,
                        revision=plan.state_revision, evidence_ids=basis.evidence_ids, policy_version=policy["version"])


def _plan_current(store, plan, issue, facts, policy):
    unmet, inspections = _source_contract(store, facts)
    unmet = list(unmet)
    basis = plan.basis
    if basis is None:
        unmet.append("legacy_plan_without_basis")
    else:
        if basis.issue_revision_after_plan != issue.state_revision:
            unmet.append("plan_issue_revision_stale")
        for field in ("classification", "jurisdiction", "geocode"):
            current = getattr(facts, field)
            if current is None or getattr(basis, field) != _reference(current):
                unmet.append("plan_facts_stale")
        if (basis.inspections != inspections or facts.classification is None
                or basis.evidence_ids != facts.classification.supporting_evidence_ids):
            unmet.append("plan_evidence_stale")
    if plan.policy_version != policy["version"]:
        unmet.append("plan_policy_stale")
    classified = facts.classification
    computed_quote = None
    if classified is not None:
        try:
            computed_quote = quote_cents(policy, classified.category, large_objects=classified.large_object_count)
            if (plan.quote_cents != computed_quote or plan.service_type != classified.category
                    or plan.large_objects != classified.large_object_count
                    or plan.required_equipment != tuple(required_equipment(policy, classified.category))
                    or plan.crew_count != 2 or plan.proof_requirements != c.ProofRequirements()
                    or plan.primary_target != classified.primary_target or plan.scope != classified.full_cleanup_scope
                    or plan.work_area != classified.marked_work_area or facts.geocode is None
                    or plan.dispatch_location != facts.geocode.location):
                unmet.append("plan_contract_mismatch")
        except ValueError:
            unmet.append("service_scope_not_priceable")
    return unmet, computed_quote


def list_eligible_vendors(store: Store, *, plan_id: str, actor: c.ActorContext,
                         policy_path: Path = DEFAULT_POLICY_PATH) -> c.ToolResult[VendorOptions]:
    policy = load_policy(policy_path)
    boundary = AccessBoundary(actor, policy["district"])
    boundary.require(Action.LIST_VENDORS)
    # A coherent read snapshot, with no revision, ledger or request changes.
    with store.transaction():
        plan = store.get_plan(plan_id)
        issue = boundary.issue(store, plan.issue_id)
        facts = store.current_issue_facts(plan.issue_id)
        unmet, _quote = _plan_current(store, plan, issue, facts, policy)
        if unmet:
            return c.ToolResult[VendorOptions](outcome="DENIED", reason_code="PLAN_NOT_CURRENT", unmet=tuple(unmet))
        eligible = [v for v in store.list_vendors() if not vendor_eligibility(policy,
            v.model_dump(), category=plan.service_type, required_equipment=list(plan.required_equipment))]
        by_id = {v.id: v for v in eligible}
        ordered = tuple(by_id[v["id"]] for v in rank_vendors([v.model_dump() for v in eligible]))
        return c.ToolResult[VendorOptions](outcome="OK", data=VendorOptions(plan=plan,
            issue_revision=issue.state_revision, vendors=ordered))


def dispatch_vendor(store: Store, *, plan_id: str, vendor_id: str,
                    context: c.MutationContext, policy_path: Path = DEFAULT_POLICY_PATH) -> c.RequestReceipt:
    policy = load_policy(policy_path)
    AccessBoundary(context.actor, policy["district"]).require(Action.DISPATCH)
    plan = store.get_plan(plan_id)
    _authorize(store, context, policy, Action.DISPATCH, plan.issue_id)
    fingerprint = _fingerprint(context, plan_id=plan_id, vendor_id=vendor_id)
    with store.transaction() as tx:
        plan = store.get_plan(plan_id)
        _authorize(store, context, policy, Action.DISPATCH, plan.issue_id)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            return previous
        issue = tx.require_issue(plan.issue_id)
        facts = store.current_issue_facts(issue.id)
        unmet, computed_quote = _plan_current(store, plan, issue, facts, policy)
        if issue.state_revision != context.expected_revision:
            unmet.append("stale_issue_revision")
        if store.active_job_for_issue(issue.id) is not None or store.job_for_plan(plan.id) is not None:
            unmet.append("job_already_exists")
        if facts.jurisdiction is None or facts.jurisdiction.responsibility != "district":
            unmet.append("responsibility_not_district")
        if facts.unresolved_hazards:
            unmet.append("unresolved_hazards")
        location = facts.geocode.location if facts.geocode else None
        if location is None or location.accuracy_m is None or location.accuracy_m > policy["precise_geocode_max_m"]:
            unmet.append("location_not_precise")
        try:
            budget_record = store.get_budget(policy["district"])
            if (budget_record.policy_version != policy["version"]
                    or budget_record.initial_cents != policy["budget_cents"]):
                raise ValueError("budget does not match configured allocation")
            budget = store.budget_availability(budget_record.id)
        except (KeyError, ValueError):
            budget = None
            unmet.append("budget_unavailable_or_inconsistent")
        try:
            vendor = store.get_vendor(vendor_id).model_dump()
        except KeyError:
            vendor = {}
            unmet.append("vendor_not_found")
        score = store.current_evidence_score(issue.id)
        gate = dispatch_gate(policy, issue_status=issue.status, evidence_total=score.total,
            category=facts.classification.category if facts.classification else plan.service_type,
            hazards=facts.unresolved_hazards, coordinates=location.model_dump() if location else None,
            vendor=vendor, required_equipment=list(plan.required_equipment),
            quote=computed_quote or plan.quote_cents, available_cents=budget.available_cents if budget else 0)
        unmet.extend(gate.unmet)
        audit = c.DispatchAuditFacts(plan_id=plan.id, vendor_id=vendor_id,
            expected_issue_revision=context.expected_revision, actual_issue_revision=issue.state_revision,
            computed_quote_cents=computed_quote, budget=budget,
            unresolved_hazards=facts.unresolved_hazards, hazard_sources=facts.hazard_sources)
        if unmet:
            return _receipt(tx, context, fingerprint, issue, "DISPATCH_DENIED", record_id=plan.id,
                revision=plan.state_revision, unmet=tuple(dict.fromkeys(unmet)), dispatch=audit,
                evidence_ids=plan.basis.evidence_ids if plan.basis else (), score=score, policy_version=policy["version"])
        job = c.JobRecord(id=str(uuid4()), issue_id=issue.id, plan_id=plan.id, vendor_id=vendor_id,
            price_cents=plan.quote_cents, created_at=datetime.now(UTC))
        tx.insert_job(job)
        reservation = c.ReservationRecord(id=str(uuid4()), budget_id=budget.budget_id,
            issue_id=issue.id, job_id=job.id, amount_cents=job.price_cents, created_at=datetime.now(UTC))
        tx.insert_reservation(reservation)
        updated = issue.model_copy(update={"status": "RESOLUTION_ACTIVE", "state_revision": issue.state_revision + 1})
        tx.replace_issue(updated, issue.state_revision)
        receipt = _receipt(tx, context, fingerprint, updated, "SIMULATED_DISPATCH", record_id=job.id,
            revision=job.state_revision, job_id=job.id, dispatch=audit.model_copy(update={"reservation_id": reservation.id}),
            evidence_ids=plan.basis.evidence_ids, score=score, policy_version=policy["version"])
        tx.append_ledger(c.LedgerEntry(id=str(uuid4()), budget_id=budget.budget_id, job_id=job.id,
            reservation_id=reservation.id, kind="RESERVE", amount_cents=reservation.amount_cents,
            event_id=receipt.result.event_ids[0], created_at=datetime.now(UTC)))
        return receipt
