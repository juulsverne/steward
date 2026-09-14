import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ApiError, mutate, newIdempotencyKey, pollUntil, read, type Envelope } from "../api/client";
import { exceptionKind, exceptionStatus, invocationIsTerminal, requirementLabel } from "../api/labels";
import type { BudgetAvailability, ExceptionDetail, InvocationStatus, PendingEntityResult, RuntimeStatus } from "../types";
import { ActionButton } from "./ActionButton";
import { ProofPair } from "./EvidenceComparison";
import { KeyValue } from "./KeyValue";
import { Money } from "./Money";
import { Notice } from "./Notice";
import { Points } from "./Points";
import { ErrorNotice, PendingState, SavedState } from "./States";
import { StatusBadge } from "./StatusBadge";

type Submit = { phase: "idle" | "sending" | "saved" | "processing" | "exhausted" | "stale" | "error"; status: InvocationStatus | null; error: unknown; eventIds: number[]; pollError: unknown; invocationId: string | null };

export function ExceptionDetailPanel({ exceptionId, onChanged }: { exceptionId: string; onChanged: () => void }) {
  const [state, setState] = useState<{ status: "pending" | "ready" | "error"; data: ExceptionDetail | null; error: unknown }>({ status: "pending", data: null, error: null });
  const [budget, setBudget] = useState<BudgetAvailability | null>(null);
  const [submit, setSubmit] = useState<Submit>({ phase: "idle", status: null, error: null, eventIds: [], pollError: null, invocationId: null });
  const key = useRef<string | null>(null);
  const pollAbort = useRef<AbortController | null>(null); const mounted = useRef(true);
  const load = useCallback(async (signal?: AbortSignal) => {
    try { const data = await read<ExceptionDetail>(`/api/exceptions/${encodeURIComponent(exceptionId)}`, { signal });
      if (signal?.aborted || !mounted.current) return;
      setState({ status: "ready", data, error: null });
      if (data.kind === "budget") {
        const budget = await read<BudgetAvailability>("/api/budget", { signal }).catch(() => null);
        if (!signal?.aborted && mounted.current) setBudget(budget);
      }
    } catch (error) { if (!signal?.aborted && mounted.current) setState((s) => ({ status: "error", data: s.data, error: error instanceof ApiError ? error : new Error(String(error)) })); }
  }, [exceptionId]);
  useEffect(() => {
    const controller = new AbortController(); mounted.current = true;
    key.current = null; pollAbort.current?.abort(); setSubmit({ phase: "idle", status: null, error: null, eventIds: [], pollError: null, invocationId: null }); void load(controller.signal);
    return () => { mounted.current = false; controller.abort(); pollAbort.current?.abort(); };
  }, [load]);

  const refreshInvocation = async (invocationId: string) => {
    pollAbort.current?.abort();
    const controller = new AbortController(); pollAbort.current = controller;
    setSubmit((s) => ({ ...s, phase: "processing", pollError: null }));
    try {
      const polled = await pollUntil(
        () => read<RuntimeStatus>(`/api/invocations/${encodeURIComponent(invocationId)}`, { signal: controller.signal }),
        (v) => invocationIsTerminal(v.status), { maxMs: 90000, signal: controller.signal },
      );
      if (!controller.signal.aborted) setSubmit((s) => ({ ...s, phase: polled.exhausted ? "exhausted" : "processing", status: polled.value.status }));
    } catch (error) {
      if (!controller.signal.aborted) setSubmit((s) => ({ ...s, phase: "saved", status: null, pollError: error }));
    }
  };

  const requestCompletion = async (ex: ExceptionDetail) => {
    if (!ex.submission_id || ex.job_revision === null || ex.job_revision === undefined) return;
    key.current ??= newIdempotencyKey("request-completion");
    setSubmit({ phase: "sending", status: null, error: null, eventIds: [], pollError: null, invocationId: null });
    let result: Envelope<PendingEntityResult>;
    try {
      result = await mutate<PendingEntityResult>(`/api/exceptions/${encodeURIComponent(ex.id)}/request-completion`,
        { submission_id: ex.submission_id, expected_job_revision: ex.job_revision }, { idempotencyKey: key.current, expectedRevision: ex.state_revision });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) { setSubmit({ phase: "stale", status: null, error, eventIds: [], pollError: null, invocationId: null }); key.current = null; void load(); onChanged(); }
      else setSubmit({ phase: "error", status: null, error, eventIds: [], pollError: null, invocationId: null });
      return;
    }
    if (!mounted.current) return;
    // The decision is already durably saved server-side at this point, so a
    // failure while polling for the resumed invocation's status must not be
    // reported as "not saved" - it keeps phase "saved" and surfaces a
    // separate, recoverable notice instead.
    setSubmit({ phase: "saved", status: null, error: null, eventIds: result.event_ids, pollError: null, invocationId: result.data?.invocation_id ?? null });
    onChanged();
    const invocationId = result.data?.invocation_id;
    if (invocationId) await refreshInvocation(invocationId);
    void load();
  };

  if (state.status === "pending" && !state.data) return <PendingState />;
  const ex = state.data;
  if (!ex) return <ErrorNotice error={state.error} onRetry={() => void load()} />;
  const st = exceptionStatus(ex.status);
  const canAct = ex.kind === "completion" && ex.status === "PENDING" && ex.allowed_next.includes("request_completion") && submit.phase !== "saved" && submit.phase !== "processing" && submit.phase !== "exhausted";
  return (
    <div className="exception stack-6">
      <div className="stack-2">
        <div className="row"><StatusBadge label={st.label} tone={st.tone} /><StatusBadge label={exceptionKind(ex.kind)} tone="neutral" /></div>
        <KeyValue items={[
          { label: "Issue", value: <Link to={`/issues/${ex.issue_id}`}>{ex.issue_id}</Link> },
          ...(ex.job_id ? [{ label: "Job", value: ex.job_id }] : []), ...(ex.submission_id ? [{ label: "Submission", value: ex.submission_id }] : []),
          { label: "Scope", value: ex.scope }, { label: "Primary target", value: ex.primary_target ?? "Unknown" }, { label: "Work area", value: ex.work_area ?? "Unknown" },
          { label: "Reason", value: requirementLabel(ex.reason_code) },
        ]} />
      </div>
      {ex.kind === "completion" ? (
        <>
          <Notice tone="warning" title="Failed requirement">
            <ul>{(ex.unmet.length ? ex.unmet : ex.score_gate?.unmet ?? []).map((u) => <li key={u}>Failed: {requirementLabel(u)}</li>)}</ul>
            {ex.total !== null && ex.total !== undefined && <p><Points value={ex.total} threshold={ex.payment_threshold} style="of" suffix="for payment" /></p>}
          </Notice>
          <ProofPair beforeId={ex.before_evidence_id ?? null} afterId={ex.after_evidence_id ?? null} jobId={ex.job_id ?? null} />
          {ex.components && <KeyValue items={Object.entries(ex.components).map(([k, v]) => ({ label: requirementLabel(k), value: v as number }))} />}
          {ex.prerequisites.length > 0 && <ul className="small">{ex.prerequisites.map((g) => <li key={g.name}>{requirementLabel(g.name)}: {g.allowed ? "passed" : `failed (${g.unmet.map(requirementLabel).join(", ")})`}</li>)}</ul>}
        </>
      ) : (
        <Notice tone="info" title="Recorded for the operator">
          <p>{requirementLabel(ex.reason_code)}. No automatic action is offered for this kind of exception.</p>
          {ex.kind === "budget" && budget && <p>Budget now: <Money cents={budget.available_cents} /> available, <Money cents={budget.reserved_cents} /> reserved, <Money cents={budget.spent_cents} /> spent.</p>}
        </Notice>
      )}
      {submit.phase === "stale" && <Notice tone="warning" title="This item changed since you opened it" role="alert">The newest saved state is shown. Review it before acting again.</Notice>}
      {submit.phase === "error" && <ErrorNotice error={submit.error} title="Request not saved" />}
      {(submit.phase === "saved" || submit.phase === "processing" || submit.phase === "exhausted") && (
        <div className="stack-2">
          <SavedState phase="saved" detail={<><span>Decision saved</span>{submit.eventIds.length ? <span className="muted small">, event {submit.eventIds.join(", ")}</span> : null}</>} />
          {submit.phase !== "saved" && <SavedState phase={submit.phase === "exhausted" ? "exhausted" : "processing"} status={submit.status} detail="Processing resumed" onRefresh={submit.invocationId ? () => void refreshInvocation(submit.invocationId!) : undefined} />}
          {submit.phase === "saved" && Boolean(submit.pollError) && (
            <Notice tone="warning" title="Saved; could not confirm processing status">
              <ActionButton variant="quiet" onClick={() => submit.invocationId && void refreshInvocation(submit.invocationId)}>Refresh</ActionButton>
            </Notice>
          )}
        </div>
      )}
      {ex.kind === "completion" && ex.status === "PENDING" && (
        <div className="exception__action">
          <ActionButton onClick={() => void requestCompletion(ex)} disabled={!canAct} pending={submit.phase === "sending"} pendingLabel="Saving decision">Request completion</ActionButton>
          <p className="small muted">Asks the crew to finish the work on the same job, quote and reservation. Payment stays blocked until fresh proof verifies.</p>
        </div>
      )}
    </div>
  );
}
