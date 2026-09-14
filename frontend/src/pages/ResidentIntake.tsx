import { useEffect, useRef, useState } from "react";
import "./ResidentIntake.css";
import { ApiError, newIdempotencyKey, pollUntil, read, upload } from "../api/client";
import { invocationIsTerminal } from "../api/labels";
import { loadSession, useSession } from "../api/session";
import { ActionButton } from "../components/ActionButton";
import { KeyValue } from "../components/KeyValue";
import { Notice } from "../components/Notice";
import { PageHeader } from "../components/PageHeader";
import { RequirePersona } from "../components/RequirePersona";
import { ErrorNotice, SavedState } from "../components/States";
import { Timestamp } from "../components/Timestamp";
import type { IntakeReceiptView, InvocationStatus, ReceiptStatusView } from "../types";

type Attempt = { key: string; form: FormData };

export function ResidentIntake() {
  const session = useSession();
  useEffect(() => { if (session.status === "loading") void loadSession(); }, [session.status]);
  return <RequirePersona allow={["resident", "crew", "operator"]}><IntakeContent /></RequirePersona>;
}

function IntakeContent() {
  const session = useSession();
  const [description, setDescription] = useState(""); const [location, setLocation] = useState(""); const [when, setWhen] = useState(""); const [unknown, setUnknown] = useState(false);
  const [photo, setPhoto] = useState<File | null>(null);
  const [phase, setPhase] = useState<"idle" | "sending" | "saved" | "polling" | "exhausted" | "error">("idle");
  const [receipt, setReceipt] = useState<IntakeReceiptView | null>(null); const [status, setStatus] = useState<InvocationStatus | null>(null); const [reason, setReason] = useState<string | null>(null); const [error, setError] = useState<unknown>(null); const [pollError, setPollError] = useState<unknown>(null);
  const attempt = useRef<Attempt | null>(null); const pollAbort = useRef<AbortController | null>(null); const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; pollAbort.current?.abort(); }; }, []);

  const discardAttempt = () => {
    attempt.current = null;
    if (phase === "error") { setPhase("idle"); setError(null); }
  };
  const refresh = async (currentReceipt: IntakeReceiptView | null = receipt) => {
    if (!currentReceipt) return;
    pollAbort.current?.abort();
    const controller = new AbortController(); pollAbort.current = controller;
    setPhase("polling"); setPollError(null);
    try {
      const polled = await pollUntil(
        () => read<ReceiptStatusView>(`/api/signals/${encodeURIComponent(currentReceipt.signal_id)}/receipt`, { signal: controller.signal }),
        (v) => invocationIsTerminal(v.processing), { maxMs: 90000, signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      setStatus(polled.value.processing); setReason(polled.value.reason_code ?? null); setPhase(polled.exhausted ? "exhausted" : "polling");
    } catch (pollFailure) {
      if (!controller.signal.aborted) { setPhase("saved"); setPollError(pollFailure); }
    }
  };
  const submit = async () => {
    if (!description.trim() || !location.trim()) { setError(new Error("Description and location are required.")); setPhase("error"); return; }
    if (!attempt.current) {
      const form = new FormData(); form.set("description", description.trim()); form.set("location", location.trim());
      if (!unknown && when) form.set("observed_at", new Date(when).toISOString());
      if (photo) form.set("image", photo, photo.name);
      attempt.current = { key: newIdempotencyKey("report"), form };
    }
    const current = attempt.current;
    setPhase("sending"); setError(null);
    try {
      const result = await upload<IntakeReceiptView>("/api/signals", current.form, { idempotencyKey: current.key });
      if (!mounted.current) return;
      const saved = result.data!; setReceipt(saved); setPhase("saved");
      await refresh(saved);
    } catch (submitFailure) {
      if (!mounted.current) return;
      setError(submitFailure); setPhase("error");
      if (submitFailure instanceof ApiError && submitFailure.status === 409) attempt.current = null;
    }
  };

  if (receipt) return (
    <div className="page intake">
      <PageHeader eyebrow="Resident" title="Report saved" />
      <div className="card"><div className="card__body stack-4">
        <KeyValue items={[{ label: "Receipt", value: <code>{receipt.receipt_id}</code> }, { label: "Received", value: <Timestamp value={receipt.received_at} /> }]} />
        <SavedState phase={phase === "exhausted" ? "exhausted" : "processing"} status={status ?? receipt.processing as InvocationStatus} detail="Steward is reviewing the report" onRefresh={() => void refresh()} />
        {pollError !== null && <ErrorNotice error={pollError} title="Report saved; status unavailable" onRetry={() => void refresh()} />}
        {reason && /LOCAT|GEOCODE|ADDRESS/i.test(reason) && <Notice tone="info" title="Received, not yet located">The address is outside the demo set, so it is saved without a location until it can be resolved.</Notice>}
        <p className="small muted">If the address was outside the demo set, the report is still saved but will not show a location on the map until it can be resolved.</p>
        <p className="small muted">No further status page exists. Nothing about other reporters is shown.</p>
      </div></div>
    </div>
  );
  const disabled = phase === "sending";
  return (
    <div className="page intake">
      <PageHeader eyebrow="Resident" title="Report a condition" meta={session.session?.notice ? <span>{session.session.notice}</span> : undefined} />
      <form className="card" onSubmit={(e) => { e.preventDefault(); void submit(); }}><div className="card__body stack-4">
        <div className="field"><label htmlFor="desc">What did you see?</label><textarea id="desc" value={description} onChange={(e) => { discardAttempt(); setDescription(e.target.value); }} disabled={disabled} required /></div>
        <div className="field"><label htmlFor="loc">Where?</label><input id="loc" type="text" value={location} onChange={(e) => { discardAttempt(); setLocation(e.target.value); }} disabled={disabled} required /><p className="field__help">Street address or nearest intersection. Addresses outside the demo set are saved but cannot be located yet.</p></div>
        <div className="field"><label htmlFor="when">When did you see it? (optional)</label><input id="when" type="datetime-local" value={when} onChange={(e) => { discardAttempt(); setWhen(e.target.value); }} disabled={unknown || disabled} /><label className="row small"><input type="checkbox" checked={unknown} onChange={(e) => { discardAttempt(); setUnknown(e.target.checked); if (e.target.checked) setWhen(""); }} disabled={disabled} /> I don't know</label></div>
        <div className="field"><label htmlFor="photo">Photo (optional)</label><input id="photo" type="file" accept="image/jpeg,image/png" onChange={(e) => { discardAttempt(); setPhoto(e.target.files?.[0] ?? null); }} disabled={disabled} />{photo && <p className="field__help">Selected: {photo.name}</p>}</div>
        {phase === "error" && <ErrorNotice error={error} title="Report not saved, your entries are kept" />}
        <ActionButton type="submit" pending={disabled} pendingLabel="Sending">Send report</ActionButton>
      </div></form>
    </div>
  );
}
