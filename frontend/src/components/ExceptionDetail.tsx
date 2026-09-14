import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { ApiError, mutate, newIdempotencyKey, pollUntil, read } from "../api/client";
import { exceptionKind, exceptionStatus, invocationIsTerminal, requirementLabel } from "../api/labels";
import type { BudgetAvailability, ExceptionDetail, InvocationStatus, PendingEntityResult, RuntimeStatus } from "../types";
import { ActionButton } from "./ActionButton";
import { EvidenceImage } from "./EvidenceImage";
import { KeyValue } from "./KeyValue";
import { Money } from "./Money";
import { Notice } from "./Notice";
import { Points } from "./Points";
import { ErrorNotice, PendingState, SavedState } from "./States";
import { StatusBadge } from "./StatusBadge";

export function ProofPair({ beforeId, afterId, jobId, beforeObservedAt, afterObservedAt }: { beforeId: string | null; afterId: string | null; jobId: string | null; beforeObservedAt?: string | null; afterObservedAt?: string | null }) {
  return (
    <div className="proof-pair">
      {beforeId ? <EvidenceImage evidenceId={beforeId} role="Before" observedAt={beforeObservedAt ?? null} jobId={jobId} /> : <p className="muted">No before photo</p>}
      {afterId ? <EvidenceImage evidenceId={afterId} role="After" observedAt={afterObservedAt ?? null} jobId={jobId} /> : <p className="muted">No after photo</p>}
    </div>
  );
}

type Submit = { phase: "idle" | "sending" | "saved" | "processing" | "exhausted" | "stale" | "error"; status: InvocationStatus | null; error: unknown; eventIds: number[] };

export function ExceptionDetailPanel({ exceptionId, onChanged }: { exceptionId: string; onChanged: () => void }) {
  const [state, setState] = useState<{ status: "pending" | "ready" | "error"; data: ExceptionDetail | null; error: unknown }>({ status: "pending", data: null, error: null });
  const [budget, setBudget] = useState<BudgetAvailability | null>(null);
  const [submit, setSubmit] = useState<Submit>({ phase: "idle", status: null, error: null, eventIds: [] });
  const key = useRef<string | null>(null);
  const load = useCallback(async () => {
    try { const data = await read<ExceptionDetail>(`/api/exceptions/${encodeURIComponent(exceptionId)}`); setState({ status: "ready", data, error: null });
      if (data.kind === "budget") setBudget(await read<BudgetAvailability>("/api/budget").catch(() => null)); }
    catch (error) { setState((s) => ({ status: "error", data: s.data, error: error instanceof ApiError ? error : new Error(String(error)) })); }
  }, [exceptionId]);
  useEffect(() => { key.current = null; setSubmit({ phase: "idle", status: null, error: null, eventIds: [] }); void load(); }, [load]);

  const requestCompletion = async (ex: ExceptionDetail) => {
    if (!ex.submission_id || ex.job_revision === null || ex.job_revision === undefined) return;
    key.current ??= newIdempotencyKey("request-completion");
    setSubmit({ phase: "sending", status: null, error: null, eventIds: [] });
    try {
      const result = await mutate<PendingEntityResult>(`/api/exceptions/${encodeURIComponent(ex.id)}/request-completion`,
        { submission_id: ex.submission_id, expected_job_revision: ex.job_revision }, { idempotencyKey: key.current, expectedRevision: ex.state_revision });
      setSubmit({ phase: "saved", status: null, error: null, eventIds: result.event_ids });
      onChanged();
      const invocationId = result.data?.invocation_id;
      if (invocationId) {
        setSubmit((s) => ({ ...s, phase: "processing" }));
        const polled = await pollUntil(() => read<RuntimeStatus>(`/api/invocations/${encodeURIComponent(invocationId)}`), (v) => invocationIsTerminal(v.status), { maxMs: 90000 });
        setSubmit((s) => ({ ...s, phase: polled.exhausted ? "exhausted" : "processing", status: polled.value.status }));
      }
      void load();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) { setSubmit({ phase: "stale", status: null, error, eventIds: [] }); key.current = null; void load(); onChanged(); }
      else setSubmit({ phase: "error", status: null, error, eventIds: [] });
    }
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
          {submit.phase !== "saved" && <SavedState phase={submit.phase === "exhausted" ? "exhausted" : "processing"} status={submit.status} detail="Processing resumed" onRefresh={() => void load()} />}
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
