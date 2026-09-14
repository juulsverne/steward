import { useEffect, useRef, useState } from "react";
import { ApiError, newIdempotencyKey, pollUntil, read, upload } from "../api/client";
import { invocationIsTerminal } from "../api/labels";
import type { CrewJobView, EntityResult, InvocationStatus, ProofReceiptView } from "../types";
import { ActionButton } from "./ActionButton";
import { ErrorNotice, SavedState } from "./States";

type Attempt = { key: string; form: FormData; expectedRevision: number };

export function ProofForm({ job, onSubmitted }: { job: CrewJobView; onSubmitted: () => void }) {
  const [rework] = useState(() => job.status === "REWORK_REQUIRED");
  const [before, setBefore] = useState<File | null>(null); const [after, setAfter] = useState<File | null>(null);
  const [beforeAt, setBeforeAt] = useState(""); const [afterAt, setAfterAt] = useState("");
  const [phase, setPhase] = useState<"idle" | "sending" | "received" | "polling" | "exhausted" | "error">("idle");
  const [submissionId, setSubmissionId] = useState<string | null>(null); const [status, setStatus] = useState<InvocationStatus | null>(null); const [error, setError] = useState<unknown>(null); const [pollError, setPollError] = useState<unknown>(null);
  const attempt = useRef<Attempt | null>(null); const pollAbort = useRef<AbortController | null>(null); const mounted = useRef(true);
  const missing = !after ? "after photo" : !rework && !before ? "before photo" : null;
  const done = phase === "received" || phase === "polling" || phase === "exhausted";

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; pollAbort.current?.abort(); }; }, []);
  const discardAttempt = () => {
    attempt.current = null;
    if (phase === "error") { setPhase("idle"); setError(null); }
  };
  const refreshReceipt = async (id: string) => {
    pollAbort.current?.abort();
    const controller = new AbortController(); pollAbort.current = controller;
    setPhase("polling"); setPollError(null);
    try {
      const polled = await pollUntil(
        () => read<ProofReceiptView>(`/api/jobs/${encodeURIComponent(job.id)}/proofs/${encodeURIComponent(id)}/receipt`, { signal: controller.signal }),
        (v) => invocationIsTerminal(v.processing), { maxMs: 120000, signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      setStatus(polled.value.processing); setPhase(polled.exhausted ? "exhausted" : "polling"); onSubmitted();
    } catch (pollFailure) {
      if (!controller.signal.aborted) { setPhase("received"); setPollError(pollFailure); }
    }
  };
  const submit = async () => {
    if (missing) { setError(new Error(`Add the ${missing} before submitting.`)); setPhase("error"); return; }
    if (!attempt.current) {
      const form = new FormData();
      if (!rework && before) form.set("before", before, before.name);
      form.set("after", after!, after!.name);
      const metadata: Record<string, string> = {};
      if (!rework && beforeAt) metadata.before_observed_at = new Date(beforeAt).toISOString();
      if (afterAt) metadata.after_observed_at = new Date(afterAt).toISOString();
      form.set("metadata", JSON.stringify(metadata));
      attempt.current = { key: newIdempotencyKey("proof"), form, expectedRevision: job.state_revision };
    }
    const current = attempt.current;
    setPhase("sending"); setError(null);
    try {
      const result = await upload<EntityResult>(`/api/jobs/${encodeURIComponent(job.id)}/proof`, current.form, { idempotencyKey: current.key, expectedRevision: current.expectedRevision });
      if (!mounted.current) return;
      const id = result.data?.record_id ?? null; setSubmissionId(id); setPhase("received"); onSubmitted();
      if (id) await refreshReceipt(id);
    } catch (submitFailure) {
      if (!mounted.current) return;
      setError(submitFailure); setPhase("error");
      if (submitFailure instanceof ApiError && submitFailure.status === 409) attempt.current = null;
    }
  };

  return (
    <div className="proof-form stack-4">
      {!rework && (
        <div className="field"><label htmlFor="before-file">Before photo</label>
          <input id="before-file" type="file" accept="image/jpeg,image/png" onChange={(e) => { discardAttempt(); setBefore(e.target.files?.[0] ?? null); }} disabled={done || phase === "sending"} />
          {before && <p className="field__help">Selected: {before.name}</p>}
          <label htmlFor="before-at" className="field__label">Before photo taken at (optional)</label>
          <input id="before-at" type="datetime-local" value={beforeAt} onChange={(e) => { discardAttempt(); setBeforeAt(e.target.value); }} disabled={done || phase === "sending"} /></div>
      )}
      <div className="field"><label htmlFor="after-file">After photo</label>
        <input id="after-file" type="file" accept="image/jpeg,image/png" onChange={(e) => { discardAttempt(); setAfter(e.target.files?.[0] ?? null); }} disabled={done || phase === "sending"} />
        {after && <p className="field__help">Selected: {after.name}</p>}
        <label htmlFor="after-at" className="field__label">After photo taken at (optional)</label>
        <input id="after-at" type="datetime-local" value={afterAt} onChange={(e) => { discardAttempt(); setAfterAt(e.target.value); }} disabled={done || phase === "sending"} /></div>
      {rework && <p className="small muted">The original before photo is kept on this job. Submit only a fresh after photo.</p>}
      {phase === "error" && <ErrorNotice error={error} title="Proof not submitted, your selections are kept" />}
      {done && <>
        <SavedState phase={phase === "exhausted" ? "exhausted" : "processing"} status={status} detail={`Received, submission ${submissionId}`} onRefresh={submissionId ? () => void refreshReceipt(submissionId) : undefined} />
        {pollError !== null && <ErrorNotice error={pollError} title="Proof saved; status unavailable" onRetry={submissionId ? () => void refreshReceipt(submissionId) : undefined} />}
      </>}
      {!done && <ActionButton onClick={() => void submit()} pending={phase === "sending"} pendingLabel="Uploading">Submit proof</ActionButton>}
    </div>
  );
}
