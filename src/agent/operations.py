"""Policy-owning B5 operations. No model, adapter, crew action or payment runs here."""
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from . import contracts as c
from .actors import AccessBoundary, Action
from .images import ImageStorage, NormalizedImage, UploadError
from .intake import stable_id
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
from .store import IdempotencyConflict, RevisionConflict, Store, request_fingerprint


class VendorOptions(c.Record):
    plan: c.PlanRecord
    issue_revision: c.Nonnegative
    vendors: tuple[c.VendorRecord, ...]


@dataclass(frozen=True)
class ProofImages:
    """Already decoded, normalized private images. These are never HTTP contracts."""

    before: NormalizedImage | None
    after: NormalizedImage
    before_observed_at: datetime | None
    after_observed_at: datetime | None
    before_provenance: c.Provenance | None
    after_provenance: c.Provenance
    before_observed_supplied: bool = False


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


def _crew_authorize(store: Store, context: c.MutationContext, action: Action, job_id: str) -> c.JobRecord:
    if context.operation != action.value:
        raise ValueError("operation does not match mutation")
    if context.expected_revision is None:
        raise ValueError("expected job revision is required")
    boundary = AccessBoundary(context.actor, "south_loop_demo")
    boundary.require(action)
    return boundary.require_job(store, job_id)


def _crew_fingerprint(context: c.MutationContext, *, job_id: str, **body) -> str:
    return request_fingerprint(body | {"job_id": job_id, "actor": context.actor.model_dump(mode="json"),
        "expected_revision": context.expected_revision})


def _crew_receipt(tx, context: c.MutationContext, fingerprint: str, job: c.JobRecord, *,
                  record_id: str, event: c.EventRecord, evidence_ids=()) -> c.RequestReceipt:
    receipt = c.RequestReceipt(id=str(uuid4()), operation=context.operation, actor_id=context.actor.actor_id,
        idempotency_key=context.idempotency_key, request_sha256=fingerprint, issue_id=job.issue_id,
        job_id=job.id, created_at=datetime.now(UTC), result=c.ToolResult[c.EntityResult](outcome="OK",
            data=c.EntityResult(record_id=record_id, state_revision=job.state_revision),
            evidence_ids=tuple(evidence_ids), event_ids=(event.id,)))
    tx.save_request(receipt)
    return receipt


def _crew_event(tx, *, job: c.JobRecord, context: c.MutationContext, event_type: str,
                record_id: str, summary: str, evidence_ids=(), submission_id: str | None = None) -> c.EventRecord:
    plan = tx.store.get_plan(job.plan_id)
    return tx.append_event(c.NewEvent(issue_id=job.issue_id, job_id=job.id, event_type=event_type,
        timestamp=datetime.now(UTC), actor=context.actor, state_revision=job.state_revision,
        policy_version=plan.policy_version, payload=c.EventFacts(summary=summary, outcome="OK",
            record_id=record_id, submission_id=submission_id, evidence_ids=tuple(evidence_ids), simulated=True)))


def accept_job(store: Store, *, job_id: str, context: c.MutationContext) -> c.RequestReceipt:
    _crew_authorize(store, context, Action.ACCEPT_JOB, job_id)
    fingerprint = _crew_fingerprint(context, job_id=job_id)
    with store.transaction() as tx:
        _crew_authorize(store, context, Action.ACCEPT_JOB, job_id)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            return previous
        job = tx.require_job(job_id, context.expected_revision)
        if job.status != "POSTED":
            raise RevisionConflict("job is not awaiting crew acceptance")
        job = job.model_copy(update={"status": "ASSIGNED", "accepted_at": datetime.now(UTC),
                                     "state_revision": job.state_revision + 1})
        tx.replace_job(job, context.expected_revision)
        event = _crew_event(tx, job=job, context=context, event_type="CREW_ACCEPTED", record_id=job.id,
                            summary="Crew accepted assigned job")
        return _crew_receipt(tx, context, fingerprint, job, record_id=job.id, event=event)


def check_in(store: Store, *, job_id: str, location: c.LocationRecord,
             claimed_at: datetime | None, context: c.MutationContext) -> c.RequestReceipt:
    _crew_authorize(store, context, Action.CHECK_IN, job_id)
    fingerprint = _crew_fingerprint(context, job_id=job_id, location=location.model_dump(mode="json"),
                                    claimed_at=claimed_at.isoformat() if claimed_at else None)
    with store.transaction() as tx:
        _crew_authorize(store, context, Action.CHECK_IN, job_id)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            return previous
        job = tx.require_job(job_id, context.expected_revision)
        if job.status != "ASSIGNED":
            raise RevisionConflict("job is not awaiting check-in")
        received_at = datetime.now(UTC)
        if claimed_at is not None and claimed_at > received_at:
            raise ValueError("claimed check-in cannot be in the future")
        job = job.model_copy(update={"status": "CHECKED_IN", "checkin_location": location,
                                     "checkin_claimed_at": claimed_at, "checked_in_at": received_at,
                                     "state_revision": job.state_revision + 1})
        tx.replace_job(job, context.expected_revision)
        event = _crew_event(tx, job=job, context=context, event_type="CREW_CHECKED_IN", record_id=job.id,
                            summary="Crew checked in")
        return _crew_receipt(tx, context, fingerprint, job, record_id=job.id, event=event)


def _proof_evidence(*, job: c.JobRecord, image: NormalizedImage, role: str, observed_at: datetime | None,
                    provenance: c.Provenance, received_at: datetime, context: c.MutationContext) -> tuple[c.EvidenceRecord, c.EvidenceAssociation]:
    evidence_id = stable_id(f"proof-{role}-evidence", context.actor.actor_id,
                            f"{job.id}:{context.idempotency_key}")
    record = c.EvidenceRecord(id=evidence_id,
        image_ref=stable_id(f"proof-{role}-image", context.actor.actor_id,
                            f"{job.id}:{context.idempotency_key}"),
        image_sha256=image.image_sha256, content_type="image/jpeg", size_bytes=image.size_bytes,
        provenance=provenance, received_at=received_at, observed_at=observed_at,
        perceptual_hash=image.image_dhash)
    association = c.EvidenceAssociation(id=stable_id(f"proof-{role}-association", context.actor.actor_id,
        f"{job.id}:{context.idempotency_key}"), evidence_id=record.id,
        role="before" if role == "before" else "completion", issue_id=job.issue_id, job_id=job.id,
        created_at=received_at)
    return record, association


def _write_proof_images(images: ProofImages, *, job_id: str, context: c.MutationContext, image_root) -> None:
    storage = ImageStorage(image_root)
    for role, image in (("before", images.before), ("after", images.after)):
        if image is None:
            continue
        ref = stable_id(f"proof-{role}-image", context.actor.actor_id, f"{job_id}:{context.idempotency_key}")
        try:
            storage.put(ref, image)
        except UploadError as error:
            if error.status == 409:
                raise IdempotencyConflict("proof image reference content conflict") from error
            raise


def submit_proof(store: Store, *, job_id: str, images: ProofImages,
                 context: c.MutationContext, image_root) -> c.RequestReceipt:
    """Commit proof state only after private normalized bytes exist; no inference runs here."""
    _crew_authorize(store, context, Action.SUBMIT_PROOF, job_id)
    if images.before_observed_at and images.before_observed_at > datetime.now(UTC):
        raise ValueError("before capture cannot be in the future")
    if images.after_observed_at and images.after_observed_at > datetime.now(UTC):
        raise ValueError("after capture cannot be in the future")
    fingerprint = _crew_fingerprint(context, job_id=job_id,
        before_sha256=images.before.image_sha256 if images.before else None,
        after_sha256=images.after.image_sha256,
        before_observed_at=images.before_observed_at.isoformat() if images.before_observed_at else None,
        after_observed_at=images.after_observed_at.isoformat() if images.after_observed_at else None,
        before_observed_supplied=images.before_observed_supplied)
    _write_proof_images(images, job_id=job_id, context=context, image_root=image_root)
    with store.transaction() as tx:
        _crew_authorize(store, context, Action.SUBMIT_PROOF, job_id)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            return previous
        job = tx.require_job(job_id, context.expected_revision)
        if store.open_completion_exception(job.id) is not None:
            raise RevisionConflict("completion exception is awaiting operator action")
        first = job.status == "CHECKED_IN"
        if first and images.before is None:
            raise ValueError("first proof requires before evidence")
        if not first and job.status != "REWORK_REQUIRED":
            raise RevisionConflict("job is not ready for proof")
        if not first and (images.before is not None or images.before_observed_supplied):
            raise ValueError("rework cannot replace original before evidence")
        received_at = datetime.now(UTC)
        if images.after_observed_at and images.after_observed_at > received_at:
            raise ValueError("after capture cannot be in the future")
        if images.before_observed_at and images.before_observed_at > received_at:
            raise ValueError("before capture cannot be in the future")
        if first:
            assert images.before is not None
            before, before_link = _proof_evidence(job=job, image=images.before, role="before",
                observed_at=images.before_observed_at, provenance=images.before_provenance or "live", received_at=received_at,
                context=context)
            tx.insert_evidence(before)
            tx.associate_evidence(before_link)
            before_id = before.id
        else:
            if job.latest_submission_id is None:
                raise ValueError("rework has no original proof")
            before_id = store.get_submission(job.latest_submission_id).before_evidence_id
        after, after_link = _proof_evidence(job=job, image=images.after, role="after",
            observed_at=images.after_observed_at, provenance=images.after_provenance, received_at=received_at,
            context=context)
        tx.insert_evidence(after)
        tx.associate_evidence(after_link)
        next_revision = job.state_revision + 1
        submission = c.SubmissionRecord(id=stable_id("submission", context.actor.actor_id,
            f"{job.id}:{context.idempotency_key}"), issue_id=job.issue_id, job_id=job.id,
            before_evidence_id=before_id, after_evidence_id=after.id, submitted_by=context.actor,
            submitted_at=received_at, job_revision=next_revision)
        tx.insert_submission(submission)
        job = job.model_copy(update={"status": "PROOF_SUBMITTED", "submitted_at": received_at,
            "latest_submission_id": submission.id, "current_verification_id": None,
            "state_revision": next_revision})
        tx.replace_job(job, context.expected_revision)
        evidence_ids = (before_id, after.id)
        event = _crew_event(tx, job=job, context=context, event_type="PROOF_SUBMITTED",
            record_id=submission.id, submission_id=submission.id, summary="Proof received", evidence_ids=evidence_ids)
        tx.insert_pending_invocation(c.PendingInvocationSpec(id=stable_id("invocation", submission.id, submission.id),
            trigger_type="PROOF_SUBMITTED", policy_version=tx.store.get_plan(job.plan_id).policy_version), event)
        return _crew_receipt(tx, context, fingerprint, job, record_id=submission.id, event=event,
                             evidence_ids=evidence_ids)


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
