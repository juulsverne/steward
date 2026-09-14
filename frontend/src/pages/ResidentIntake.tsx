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
  const [receipt, setReceipt] = useState<IntakeReceiptView | null>(null); const [status, setStatus] = useState<InvocationStatus | null>(null); const [reason, setReason] = useState<string | null>(null); const [error, setError] = useState<unknown>(null);
  const key = useRef<string | null>(null);

  const submit = async () => {
    if (!description.trim() || !location.trim()) { setError(new Error("Description and location are required.")); setPhase("error"); return; }
    key.current ??= newIdempotencyKey("report");
    const form = new FormData(); form.set("description", description.trim()); form.set("location", location.trim());
    if (!unknown && when) form.set("observed_at", new Date(when).toISOString());
    if (photo) form.set("image", photo, photo.name);
    setPhase("sending"); setError(null);
    try {
      const result = await upload<IntakeReceiptView>("/api/signals", form, { idempotencyKey: key.current });
      const r = result.data!; setReceipt(r); setPhase("saved");
      setPhase("polling");
      const polled = await pollUntil(() => read<ReceiptStatusView>(`/api/signals/${encodeURIComponent(r.signal_id)}/receipt`), (v) => invocationIsTerminal(v.processing), { maxMs: 90000 });
      setStatus(polled.value.processing); setReason(polled.value.reason_code ?? null); setPhase(polled.exhausted ? "exhausted" : "polling");
    } catch (e) { setError(e); setPhase("error"); if (e instanceof ApiError && e.status === 409) key.current = null; }
  };

  const refresh = async () => {
    if (!receipt) return;
    setPhase("polling");
    try {
      const polled = await pollUntil(() => read<ReceiptStatusView>(`/api/signals/${encodeURIComponent(receipt.signal_id)}/receipt`), (v) => invocationIsTerminal(v.processing), { maxMs: 90000 });
      setStatus(polled.value.processing); setReason(polled.value.reason_code ?? null); setPhase(polled.exhausted ? "exhausted" : "polling");
    } catch (e) { setError(e); setPhase("error"); }
  };

  if (receipt) return (
    <div className="page intake">
      <PageHeader eyebrow="Resident" title="Report saved" />
      <div className="card"><div className="card__body stack-4">
        <KeyValue items={[{ label: "Receipt", value: <code>{receipt.receipt_id}</code> }, { label: "Received", value: <Timestamp value={receipt.received_at} /> }]} />
        <SavedState phase={phase === "exhausted" ? "exhausted" : "processing"} status={status ?? receipt.processing as InvocationStatus} detail="Steward is reviewing the report" onRefresh={() => void refresh()} />
        {reason && /LOCAT|GEOCODE|ADDRESS/i.test(reason) && <Notice tone="info" title="Received, not yet located">The address is outside the demo set, so it is saved without a location until it can be resolved.</Notice>}
        <p className="small muted">If the address was outside the demo set, the report is still saved but will not show a location on the map until it can be resolved.</p>
        <p className="small muted">No further status page exists. Nothing about other reporters is shown.</p>
      </div></div>
    </div>
  );
  return (
    <div className="page intake">
      <PageHeader eyebrow="Resident" title="Report a condition" meta={session.session?.notice ? <span>{session.session.notice}</span> : undefined} />
      <form className="card" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <div className="card__body stack-4">
          <div className="field"><label htmlFor="desc">What did you see?</label><textarea id="desc" value={description} onChange={(e) => setDescription(e.target.value)} required /></div>
          <div className="field"><label htmlFor="loc">Where?</label><input id="loc" type="text" value={location} onChange={(e) => setLocation(e.target.value)} required />
            <p className="field__help">Street address or nearest intersection. Addresses outside the demo set are saved but cannot be located yet.</p></div>
          <div className="field"><label htmlFor="when">When did you see it? (optional)</label><input id="when" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} disabled={unknown} />
            <label className="row small"><input type="checkbox" checked={unknown} onChange={(e) => { setUnknown(e.target.checked); if (e.target.checked) setWhen(""); }} /> I don't know</label></div>
          <div className="field"><label htmlFor="photo">Photo (optional)</label><input id="photo" type="file" accept="image/jpeg,image/png" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />{photo && <p className="field__help">Selected: {photo.name}</p>}</div>
          {phase === "error" && <ErrorNotice error={error} title="Report not saved, your entries are kept" />}
          <ActionButton type="submit" pending={phase === "sending"} pendingLabel="Sending">Send report</ActionButton>
        </div>
      </form>
    </div>
  );
}
