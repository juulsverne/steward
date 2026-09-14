import { useRef, useState } from "react";
import { ApiError, newIdempotencyKey, pollUntil, read, upload } from "../api/client";
import { invocationIsTerminal } from "../api/labels";
import type { CrewJobView, EntityResult, InvocationStatus, ProofReceiptView } from "../types";
import { ActionButton } from "./ActionButton";
import { ErrorNotice, SavedState } from "./States";

export function ProofForm({ job, onSubmitted }: { job: CrewJobView; onSubmitted: () => void }) {
  // Freeze the rework mode for this submission's lifetime: a successful submit moves
  // job.status off REWORK_REQUIRED right away (while this form is still showing its
  // disabled saved/polling state), and re-deriving from the live prop would flip the
  // finished form back to asking for a "before" photo it never needed.
  const [rework] = useState(() => job.status === "REWORK_REQUIRED");
  const [before, setBefore] = useState<File | null>(null); const [after, setAfter] = useState<File | null>(null);
  const [beforeAt, setBeforeAt] = useState(""); const [afterAt, setAfterAt] = useState("");
  const [phase, setPhase] = useState<"idle" | "sending" | "received" | "polling" | "exhausted" | "error">("idle");
  const [submissionId, setSubmissionId] = useState<string | null>(null); const [status, setStatus] = useState<InvocationStatus | null>(null); const [error, setError] = useState<unknown>(null);
  const key = useRef<string | null>(null);
  const missing = !after ? "after photo" : !rework && !before ? "before photo" : null;

  const submit = async () => {
    if (missing) { setError(new Error(`Add the ${missing} before submitting.`)); setPhase("error"); return; }
    key.current ??= newIdempotencyKey("proof");
    const form = new FormData();
    if (!rework && before) form.set("before", before, before.name);
    form.set("after", after!, after!.name);
    const metadata: Record<string, string> = {};
    if (!rework && beforeAt) metadata.before_observed_at = new Date(beforeAt).toISOString();
    if (afterAt) metadata.after_observed_at = new Date(afterAt).toISOString();
    form.set("metadata", JSON.stringify(metadata));
    setPhase("sending"); setError(null);
    try {
      const result = await upload<EntityResult>(`/api/jobs/${encodeURIComponent(job.id)}/proof`, form, { idempotencyKey: key.current, expectedRevision: job.state_revision });
      const id = result.data?.record_id ?? null; setSubmissionId(id); setPhase("received"); onSubmitted();
      if (id) {
        setPhase("polling");
        const polled = await pollUntil(() => read<ProofReceiptView>(`/api/jobs/${encodeURIComponent(job.id)}/proofs/${encodeURIComponent(id)}/receipt`), (v) => invocationIsTerminal(v.processing), { maxMs: 120000 });
        setStatus(polled.value.processing); setPhase(polled.exhausted ? "exhausted" : "polling"); onSubmitted();
      }
    } catch (e) { setError(e); setPhase("error"); if (e instanceof ApiError && e.status === 409) key.current = null; }
  };

  const done = phase === "received" || phase === "polling" || phase === "exhausted";
  return (
    <div className="proof-form stack-4">
      {!rework && (
        <div className="field"><label htmlFor="before-file">Before photo</label>
          <input id="before-file" type="file" accept="image/jpeg,image/png" onChange={(e) => setBefore(e.target.files?.[0] ?? null)} disabled={done} />
          {before && <p className="field__help">Selected: {before.name}</p>}
          <label htmlFor="before-at" className="field__label">Before photo taken at (optional)</label>
          <input id="before-at" type="datetime-local" value={beforeAt} onChange={(e) => setBeforeAt(e.target.value)} disabled={done} /></div>
      )}
      <div className="field"><label htmlFor="after-file">After photo</label>
        <input id="after-file" type="file" accept="image/jpeg,image/png" onChange={(e) => setAfter(e.target.files?.[0] ?? null)} disabled={done} />
        {after && <p className="field__help">Selected: {after.name}</p>}
        <label htmlFor="after-at" className="field__label">After photo taken at (optional)</label>
        <input id="after-at" type="datetime-local" value={afterAt} onChange={(e) => setAfterAt(e.target.value)} disabled={done} /></div>
      {rework && <p className="small muted">The original before photo is kept on this job. Submit only a fresh after photo.</p>}
      {phase === "error" && <ErrorNotice error={error} title="Proof not submitted, your selections are kept" />}
      {done && <SavedState phase={phase === "exhausted" ? "exhausted" : "processing"} status={status} detail={`Received, submission ${submissionId}`} onRefresh={onSubmitted} />}
      {!done && <ActionButton onClick={() => void submit()} pending={phase === "sending"} pendingLabel="Uploading">Submit proof</ActionButton>}
    </div>
  );
}
