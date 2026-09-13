"""Policy-owning planning, dispatch, crew and bounded completion inspection operations."""
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from . import contracts as c
from .actors import AccessBoundary, Action
from .images import ImageStorage, NormalizedImage, UploadError, hamming
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
from .verification import FINDING_FIELDS, PAYMENT_MIN, prerequisites_pass, verification_points
from .vision import (
    VisionOutputError,
    VisionRequestBasis,
    capture_request_basis,
    inspect_pair_result,
)


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


COMPLETION_CLAIM_SECONDS = 120


def _completion_basis(*, job: c.JobRecord, submission: c.SubmissionRecord, plan: c.PlanRecord,
                      before: c.EvidenceRecord, after: c.EvidenceRecord,
                      frozen: VisionRequestBasis | None = None) -> c.CompletionInspectionBasis:
    frozen = frozen or capture_request_basis()
    configuration = hashlib.sha256(json.dumps({"model": frozen.model_id, "region": frozen.region,
        "profile": frozen.profile, "prompt": frozen.prompt_version, "schema": frozen.schema_version,
        "request": frozen.request_version, "preprocessing": frozen.preprocessing_version}, sort_keys=True).encode()).hexdigest()[:16]
    cache = hashlib.sha256(json.dumps({"before": before.image_sha256, "after": after.image_sha256,
        "target": plan.primary_target, "scope": plan.scope, "work_area": plan.work_area,
        "location": plan.dispatch_location.model_dump(mode="json") if plan.dispatch_location else None,
        "model": frozen.model_id, "region": frozen.region, "profile": frozen.profile,
        "prompt": frozen.prompt_version, "schema": frozen.schema_version,
        "request": frozen.request_version, "preprocessing": frozen.preprocessing_version,
        "configuration": configuration, "policy": plan.policy_version}, sort_keys=True).encode()).hexdigest()
    if plan.primary_target is None or plan.dispatch_location is None:
        raise ValueError("legacy plan lacks completion inspection basis")
    return c.CompletionInspectionBasis(cache_key=cache, submission_id=submission.id, plan_id=plan.id,
        before_evidence_id=before.id, after_evidence_id=after.id, before_sha256=before.image_sha256,
        after_sha256=after.image_sha256, primary_target=plan.primary_target, scope=plan.scope,
        work_area=plan.work_area, dispatch_location=plan.dispatch_location, model_id=frozen.model_id,
        region=frozen.region, profile=frozen.profile, prompt_version=frozen.prompt_version,
        schema_version=frozen.schema_version, request_version=frozen.request_version,
        preprocessing_version=frozen.preprocessing_version, configuration_version=configuration,
        policy_version=plan.policy_version, request_json=frozen.request_json)


def _distance_m(a: c.LocationRecord, b: c.LocationRecord) -> float:
    radius = 6_371_000.0
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    delta_lat, delta_lon = lat2 - lat1, math.radians(b.lon - a.lon)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return radius * 2 * math.asin(math.sqrt(value))


def _completion_checks(store: Store, *, job: c.JobRecord, submission: c.SubmissionRecord,
                       before: c.EvidenceRecord, after: c.EvidenceRecord,
                       plan: c.PlanRecord) -> c.CompletionInspectionChecks:
    distance = None
    if job.checkin_location is not None and plan.dispatch_location is not None:
        distance = _distance_m(job.checkin_location, plan.dispatch_location)
    gps = (None if distance is None or job.checkin_location is None
           or job.checkin_location.accuracy_m is None or plan.dispatch_location is None
           or plan.dispatch_location.accuracy_m is None else distance <= 30)
    ordered = (None if before.observed_at is None or after.observed_at is None
               else after.observed_at > before.observed_at)
    priors = store.prior_completion_submissions(submission.id)
    prior_after = [store.get_evidence(item.after_evidence_id) for item in priors]
    refs = []
    unresolved_reuse = bool(prior_after and not after.perceptual_hash)
    reuse = any(item.image_sha256 == after.image_sha256 for item in prior_after)
    for prior, evidence in zip(priors, prior_after, strict=True):
        distance_to_prior = None
        if after.perceptual_hash and evidence.perceptual_hash:
            distance_to_prior = hamming(after.perceptual_hash, evidence.perceptual_hash)
            reuse = reuse or distance_to_prior <= 6
        elif after.image_sha256 != evidence.image_sha256:
            unresolved_reuse = True
        refs.append(c.CompletionReference(submission_id=prior.id, job_id=prior.job_id,
            after_evidence_id=evidence.id, image_sha256=evidence.image_sha256,
            perceptual_hash=evidence.perceptual_hash, dhash_distance=distance_to_prior))
    reuse_result = None if unresolved_reuse and not reuse else reuse
    cutoff = store.proof_event_for_submission(submission.id).id
    unmet = tuple(name if ok is False else f"{name}_unknown"
        for name, ok in (("gps_within_30m", gps), ("after_later_than_before", ordered)) if ok is not True)
    if reuse_result is not False:
        unmet += ("image_reuse" if reuse_result is True else "image_reuse_unknown",)
    return c.CompletionInspectionChecks(gps_within_30m=gps, after_later_than_before=ordered,
        reuse_detected=reuse_result, distance_m=distance, checkin_location=job.checkin_location,
        dispatch_location=plan.dispatch_location, before_observed_at=before.observed_at,
        after_observed_at=after.observed_at, cutoff_event_id=cutoff, prior_completions=tuple(refs), unmet=unmet)


def _completion_authorize(store: Store, context: c.MutationContext, job_id: str, submission_id: str):
    if context.operation != Action.INSPECT.value or context.expected_revision is None:
        raise ValueError("inspection requires service operation and expected job revision")
    boundary = AccessBoundary(context.actor, "south_loop_demo")
    boundary.require(Action.INSPECT)
    job = boundary.require_job(store, job_id)
    submission = store.get_submission(submission_id)
    if submission.job_id != job.id or submission.issue_id != job.issue_id:
        raise ValueError("submission does not belong to job")
    _validated_cause(store, context, issue_id=job.issue_id, signal_id=None, job_id=job.id,
                     submission_id=submission.id)
    return job, submission


def _completion_fingerprint(context: c.MutationContext, job_id: str, submission_id: str) -> str:
    return request_fingerprint({"job_id": job_id, "submission_id": submission_id,
        "expected_revision": context.expected_revision, "actor": context.actor.model_dump(mode="json"),
        "invocation_id": context.invocation_id})


def _inspection_metadata(answer: dict, basis: c.CompletionInspectionBasis, wall_time_ms: int,
                         *, physical_count: int | None = 1) -> c.ModelRunMetadata:
    return c.ModelRunMetadata(role="image", model_id=basis.model_id, vision_model_id=basis.model_id,
        region=basis.region, prompt_version=basis.prompt_version, request_id=answer.get("request_id"),
        usage=c.ModelUsage.model_validate(answer["usage"]) if answer.get("usage") else None,
        metrics=c.ModelMetrics.model_validate(answer["metrics"]) if answer.get("metrics") else None,
        attempt_count=physical_count or None, stop_reason=answer.get("stop_reason"), wall_time_ms=wall_time_ms)


def _inspection_result(tx, context, fingerprint, attempt, *, outcome, reason=None, verification=None, event=None):
    result = c.ToolResult[c.CompletionInspectionResult](outcome=outcome, reason_code=reason,
        data=c.CompletionInspectionResult(record_id=verification.id if verification else attempt.id,
            state_revision=verification.result_job_revision if verification else None,
            attempt_id=attempt.id, job_id=attempt.job_id, submission_id=attempt.submission_id,
            verification_id=verification.id if verification else None,
            input_job_revision=verification.job_revision if verification else attempt.expected_revision,
            findings=verification.findings if verification else None,
            checks=verification.checks if verification else None,
            prerequisites=verification.prerequisites if verification else (),
            components=verification.components if verification else None,
            total=sum(verification.components.model_dump().values()) if verification else None,
            unmet=verification.unmet if verification else (), metadata=attempt.metadata,
            cached_from_id=attempt.cached_from_id, physical_call_count=attempt.physical_call_count),
        unmet=verification.unmet if verification else (),
        evidence_ids=(attempt.basis.before_evidence_id, attempt.basis.after_evidence_id),
        event_ids=(event.id,) if event else ())
    tx.save_request(c.RequestReceipt(id=str(uuid4()), operation=context.operation, actor_id=context.actor.actor_id,
        idempotency_key=context.idempotency_key, request_sha256=fingerprint, issue_id=attempt.issue_id,
        job_id=attempt.job_id, invocation_id=context.invocation_id, created_at=datetime.now(UTC), result=result))
    return result


def _attempt_context(attempt: c.CompletionInspectionAttempt) -> c.MutationContext:
    return c.MutationContext(actor=attempt.actor, operation=attempt.operation,
        idempotency_key=attempt.idempotency_key, expected_revision=attempt.expected_revision,
        invocation_id=attempt.invocation_id)


def _inspection_event(tx, attempt, *, event_type, outcome, reason=None, verification=None):
    return tx.append_event(c.NewEvent(issue_id=attempt.issue_id, job_id=attempt.job_id,
        invocation_id=attempt.invocation_id, event_type=event_type, timestamp=datetime.now(UTC),
        actor=attempt.actor, state_revision=tx.store.get_job(attempt.job_id).state_revision,
        policy_version=attempt.basis.policy_version,
        payload=c.EventFacts(summary="Completion proof inspected" if verification else "Completion inspection failed",
            outcome=outcome, reason_code=reason, record_id=verification.id if verification else attempt.id,
            submission_id=attempt.submission_id,
            evidence_ids=(attempt.basis.before_evidence_id, attempt.basis.after_evidence_id),
            unmet=verification.unmet if verification else (),
            score_components=verification.components if verification else None,
            gate_results=verification.prerequisites if verification else (), metadata=attempt.metadata)))


def _finish_inspection_error(tx, attempt, reason, *, abandoned=False, metadata=None, physical_count=None):
    final = attempt.model_copy(update={"status": "ABANDONED" if abandoned else "FINISHED",
        "outcome": "ERROR", "error_code": reason, "metadata": metadata,
        "physical_call_count": physical_count, "finished_at": datetime.now(UTC)})
    tx.finish_completion_attempt(final)
    event = _inspection_event(tx, final, event_type="COMPLETION_INSPECTION_FAILED", outcome="ERROR", reason=reason)
    return _inspection_result(tx, _attempt_context(final), final.request_sha256, final,
        outcome="ERROR", reason=reason, event=event)


def _physical_basis(basis: c.CompletionInspectionBasis) -> VisionRequestBasis:
    if basis.request_json is None:
        raise ValueError("legacy attempt lacks frozen physical request")
    frozen = VisionRequestBasis(model_id=basis.model_id, region=basis.region, profile=basis.profile,
        request_json=basis.request_json, preprocessing_version=basis.preprocessing_version)
    if (frozen.request_version, frozen.prompt_version, frozen.schema_version) != (
            basis.request_version, basis.prompt_version, basis.schema_version):
        raise ValueError("physical request identity mismatch")
    return frozen


def inspect_completion(store: Store, *, job_id: str, submission_id: str, context: c.MutationContext,
                       image_root, inspector=None) -> c.ToolResult[c.CompletionInspectionResult]:
    """Claim a frozen proof inspection, invoke once outside SQLite, then fence final state."""
    _completion_authorize(store, context, job_id, submission_id)
    fingerprint = _completion_fingerprint(context, job_id, submission_id)
    with store.transaction() as tx:
        job, submission = _completion_authorize(store, context, job_id, submission_id)
        previous = tx.lookup_request(context, fingerprint)
        if previous is not None:
            return previous.result
        existing = store.completion_attempt_for_request(context)
        if existing is not None:
            if existing.request_sha256 != fingerprint:
                raise IdempotencyConflict("idempotency key payload conflict")
            if existing.status == "RUNNING":
                if existing.expires_at > datetime.now(UTC):
                    return c.ToolResult(outcome="ERROR", reason_code="INSPECTION_IN_PROGRESS")
                return _finish_inspection_error(tx, existing, "INSPECTION_INTERRUPTED", abandoned=True)
            # Every terminal attempt is committed with its receipt. A legacy or
            # corrupt row must never be silently reused under the same unique key.
            raise ValueError("terminal inspection lacks its immutable receipt")
        if context.expected_revision != job.state_revision:
            raise RevisionConflict("stale job revision")
        if job.status not in {"PROOF_SUBMITTED", "VERIFIED"} or job.latest_submission_id != submission.id:
            raise RevisionConflict("submission is not current inspectable proof")
        if store.open_completion_exception(job.id) is not None:
            raise RevisionConflict("completion exception is open")
        before, after = store.get_evidence(submission.before_evidence_id), store.get_evidence(submission.after_evidence_id)
        plan = store.get_plan(job.plan_id)
        basis = _completion_basis(job=job, submission=submission, plan=plan, before=before, after=after)
        current_verification = store.current_verification(job.id)
        if (current_verification is not None and current_verification.basis == basis
                and current_verification.checks == _completion_checks(store, job=job, submission=submission,
                    before=before, after=after, plan=plan)):
            original = store.completion_result_receipt(current_verification.id)
            tx.save_request(c.RequestReceipt(id=str(uuid4()), operation=context.operation,
                actor_id=context.actor.actor_id, idempotency_key=context.idempotency_key,
                request_sha256=fingerprint, issue_id=job.issue_id, job_id=job.id,
                invocation_id=context.invocation_id, created_at=datetime.now(UTC), result=original.result))
            return original.result
        cached = store.cached_completion_attempt(basis.cache_key)
        running = store.running_completion_attempt(basis.cache_key)
        if running is not None:
            if running.expires_at > datetime.now(UTC):
                return c.ToolResult(outcome="ERROR", reason_code="INSPECTION_IN_PROGRESS")
            _finish_inspection_error(tx, running, "INSPECTION_INTERRUPTED", abandoned=True)
        now = datetime.now(UTC)
        attempt = c.CompletionInspectionAttempt(id=str(uuid4()), actor=context.actor, operation=context.operation,
            idempotency_key=context.idempotency_key, request_sha256=fingerprint, job_id=job.id, issue_id=job.issue_id,
            submission_id=submission.id, cache_key=basis.cache_key, basis=basis, cached_from_id=cached.id if cached else None,
            expected_revision=context.expected_revision, invocation_id=context.invocation_id,
            started_at=now, expires_at=now + timedelta(seconds=COMPLETION_CLAIM_SECONDS))
        tx.insert_completion_attempt(attempt)

    answer, metadata, findings, error_code = None, None, None, None
    invoked, physical_count = False, 0
    started = datetime.now(UTC)
    try:
        before_bytes, after_bytes = ImageStorage(image_root).open(before.image_ref), ImageStorage(image_root).open(after.image_ref)
        for raw, record in ((before_bytes, before), (after_bytes, after)):
            if hashlib.sha256(raw).hexdigest() != record.image_sha256 or len(raw) != record.size_bytes:
                raise ValueError("STORED_IMAGE_MISMATCH")
        if cached is not None:
            answer = {"findings": cached.findings.model_dump(), "usage": None, "metrics": None,
                      "request_id": None, "stop_reason": "cached"}
        else:
            physical_basis = _physical_basis(basis)
            invoked, physical_count = True, None
            answer = (inspect_pair_result(before_bytes, after_bytes, target=basis.primary_target,
                scope=basis.scope, work_area=basis.work_area, basis=physical_basis) if inspector is None
                else inspector(before_bytes, after_bytes, basis))
            physical_count = 1
        metadata = _inspection_metadata(answer, basis, int((datetime.now(UTC) - started).total_seconds() * 1000),
                                        physical_count=physical_count)
        findings = c.VisionFindings.model_validate(answer.get("findings", answer))
    except VisionOutputError as exc:
        physical_count = 1
        metadata = _inspection_metadata(exc.inspection, basis,
            int((datetime.now(UTC) - started).total_seconds() * 1000))
        error_code = "INVALID_MODEL_OUTPUT"
    except Exception as exc:  # noqa: BLE001 - no-result failures remain attempts only
        error_code = "STORED_IMAGE_MISMATCH" if str(exc) == "STORED_IMAGE_MISMATCH" else (
            "INVALID_MODEL_OUTPUT" if isinstance(exc, (ValueError, TypeError)) else "INSPECTION_FAILED")

    if invoked:
        # A result-installation rollback must not erase an observed physical call.
        # This independent immutable record never grants cache or job authority.
        with store.transaction() as tx:
            tx.insert_completion_observation(c.CompletionInspectionObservation(id=str(uuid4()),
                attempt_id=attempt.id, metadata=metadata, findings=findings, error_code=error_code,
                observed_at=datetime.now(UTC)))

    with store.transaction() as tx:
        current = store.get_completion_attempt(attempt.id)
        if current.status != "RUNNING" or current.expires_at <= datetime.now(UTC):
            if current.status == "RUNNING":
                return _finish_inspection_error(tx, current, "INSPECTION_FENCED", abandoned=True,
                    metadata=metadata, physical_count=physical_count)
            # Another request already terminalized this owner. Retain that exact
            # receipt and the separately recorded observation; never rewrite it.
            return tx.lookup_request(context, fingerprint).result
        try:
            job, submission = _completion_authorize(store, context, job_id, submission_id)
        except (ValueError, KeyError):
            return _finish_inspection_error(tx, current, "INSPECTION_CAUSE_CHANGED",
                metadata=metadata, physical_count=physical_count)
        if (job.state_revision != context.expected_revision or job.latest_submission_id != submission.id
                or job.status not in {"PROOF_SUBMITTED", "VERIFIED"}):
            return _finish_inspection_error(tx, current, "STALE_PROOF", metadata=metadata,
                                            physical_count=physical_count)
        if store.open_completion_exception(job.id) is not None:
            return _finish_inspection_error(tx, current, "COMPLETION_EXCEPTION_OPEN", metadata=metadata,
                                            physical_count=physical_count)
        if error_code is not None:
            return _finish_inspection_error(tx, current, error_code, metadata=metadata,
                                            physical_count=physical_count)
        before, after = store.get_evidence(submission.before_evidence_id), store.get_evidence(submission.after_evidence_id)
        plan = store.get_plan(job.plan_id)
        if _completion_basis(job=job, submission=submission, before=before, after=after, plan=plan,
                             frozen=_physical_basis(basis)) != basis:
            return _finish_inspection_error(tx, current, "INSPECTION_BASIS_CHANGED", metadata=metadata,
                                            physical_count=physical_count)
        checks = _completion_checks(store, job=job, submission=submission, before=before, after=after, plan=plan)
        prerequisites, finding_unmet = prerequisites_pass(findings, reuse_detected=checks.reuse_detected is True)
        if checks.reuse_detected is None:
            prerequisites = False
            finding_unmet.append("image_reuse_unknown")
        components = c.VerificationComponents(**verification_points(findings, gps_within_30m=checks.gps_within_30m is True,
            after_later_than_before=checks.after_later_than_before is True))
        unmet = tuple(dict.fromkeys((*checks.unmet, *finding_unmet,
            *(name for name in FINDING_FIELDS if getattr(findings, name) is not True))))
        total = sum(components.model_dump().values())
        next_revision = job.state_revision + 1
        verification = c.VerificationRecord(id=str(uuid4()), issue_id=job.issue_id, job_id=job.id,
            submission_id=submission.id, findings=findings, components=components,
            prerequisites=(c.GateRecord(name="completion_prerequisites", allowed=prerequisites,
                                       unmet=tuple(finding_unmet)),
                c.GateRecord(name="verification_score_min_95", allowed=total >= PAYMENT_MIN,
                             unmet=("verification_score_below_95",) if total < PAYMENT_MIN else ())),
            unmet=unmet, policy_version=basis.policy_version, metadata=metadata, inspected_at=datetime.now(UTC),
            job_revision=job.state_revision, result_job_revision=next_revision, basis=basis, checks=checks,
            attempt_id=current.id)
        final = current.model_copy(update={"status": "FINISHED", "outcome": "SUCCESS", "findings": findings,
            "metadata": metadata, "physical_call_count": physical_count,
            "cache_eligible": cached is None, "finished_at": datetime.now(UTC)})
        tx.finish_completion_attempt(final)
        tx.insert_verification(verification)
        accepted = prerequisites and total >= PAYMENT_MIN
        job = job.model_copy(update={"status": "VERIFIED" if accepted else "PROOF_SUBMITTED",
            "current_verification_id": verification.id, "state_revision": next_revision})
        tx.replace_job(job, context.expected_revision)
        event = _inspection_event(tx, final, event_type="COMPLETION_INSPECTED", outcome="OK",
                                  verification=verification)
        return _inspection_result(tx, context, fingerprint, final, outcome="OK", verification=verification, event=event)


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
