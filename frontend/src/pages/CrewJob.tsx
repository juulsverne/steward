import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import "./CrewJob.css";
import { ApiError, mutate, newIdempotencyKey, read } from "../api/client";
import { jobStatus, requirementLabel } from "../api/labels";
import { loadSession } from "../api/session";
import { ActionButton } from "../components/ActionButton";
import { KeyValue } from "../components/KeyValue";
import { Money } from "../components/Money";
import { Notice } from "../components/Notice";
import { PageHeader } from "../components/PageHeader";
import { ProofForm } from "../components/ProofForm";
import { RequirePersona } from "../components/RequirePersona";
import { SectionCard } from "../components/SectionCard";
import { ErrorNotice, PendingState } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { Timestamp } from "../components/Timestamp";
import type { CrewJobView, EntityResult } from "../types";

export function CrewJob() {
  // Standalone-page bootstrap: App.tsx normally kicks off loadSession() once at the
  // root, but this page can also be exercised on its own (route-level tests, deep
  // links before App mounts), and RequirePersona never loads the session itself.
  useEffect(() => { void loadSession(); }, []);
  return <RequirePersona allow={["crew"]}><JobContent /></RequirePersona>;
}

function JobContent() {
  const { jobId = "" } = useParams();
  const [state, setState] = useState<{ status: "pending" | "ready" | "error"; data: CrewJobView | null; error: unknown }>({ status: "pending", data: null, error: null });
  const load = useCallback(async () => {
    try { setState({ status: "ready", data: await read<CrewJobView>(`/api/jobs/${encodeURIComponent(jobId)}`), error: null }); }
    catch (error) { setState((s) => ({ status: "error", data: s.data, error: error instanceof ApiError ? error : new Error(String(error)) })); }
  }, [jobId]);
  useEffect(() => { void load(); }, [load]);
  const [busy, setBusy] = useState<"accept" | "checkin" | null>(null); const [actionError, setActionError] = useState<unknown>(null);
  const acceptKey = useRef<string | null>(null); const checkinKey = useRef<string | null>(null);
  const [lat, setLat] = useState(""); const [lon, setLon] = useState(""); const [acc, setAcc] = useState("");
  const [pendingException, setPendingException] = useState(false);
  useEffect(() => { if (!jobId) return; read<{ jobs: Array<{ id: string; pending_exception_status: string | null }> }>("/api/crew/jobs?limit=50").then((v) => setPendingException(v.jobs.find((j) => j.id === jobId)?.pending_exception_status === "PENDING")).catch(() => setPendingException(false)); }, [jobId, state.data?.state_revision]);
  // The proof step stays mounted through its own submission: submitting proof moves the
  // job's status off CHECKED_IN/REWORK_REQUIRED as soon as the reload below lands, which
  // would otherwise unmount ProofForm mid-flight and lose the "received"/polling receipt
  // it is showing. `submittedLocally` keeps the step open once this session has submitted.
  // `proofCycleKey` only changes when a *new* rework attempt begins, so that same reload
  // doesn't also force a remount that would throw away ProofForm's own local state.
  const [submittedLocally, setSubmittedLocally] = useState(false);
  const [proofCycleKey, setProofCycleKey] = useState("cycle");
  const reworkRevisionSeen = useRef<number | null>(null);
  useEffect(() => {
    if (state.data?.status === "REWORK_REQUIRED" && reworkRevisionSeen.current !== state.data.state_revision) {
      reworkRevisionSeen.current = state.data.state_revision;
      setProofCycleKey(`rework-${state.data.state_revision}`);
      setSubmittedLocally(false);
    }
  }, [state.data?.status, state.data?.state_revision]);

  const job = state.data;
  if (state.status === "pending" && !job) return <div className="page"><PageHeader eyebrow="Job" title="Job" /><PendingState /></div>;
  if (!job) return <div className="page"><PageHeader eyebrow="Job" title="Job" /><ErrorNotice error={state.error} onRetry={() => void load()} /></div>;
  const st = jobStatus(job.status);
  const accepted = job.accepted_at !== null; const checkedIn = job.checked_in_at !== null;
  const proofOpen = checkedIn && (job.status === "CHECKED_IN" || job.status === "REWORK_REQUIRED" || submittedLocally) && !pendingException;
  const act = async (which: "accept" | "checkin") => {
    if (which === "checkin" && (!lat || !lon)) { setActionError(new Error("Enter latitude and longitude before checking in.")); return; }
    setBusy(which); setActionError(null);
    try {
      if (which === "accept") { acceptKey.current ??= newIdempotencyKey("accept"); await mutate<EntityResult>(`/api/jobs/${encodeURIComponent(job.id)}/accept`, undefined, { idempotencyKey: acceptKey.current, expectedRevision: job.state_revision }); }
      else { checkinKey.current ??= newIdempotencyKey("checkin");
        await mutate<EntityResult>(`/api/jobs/${encodeURIComponent(job.id)}/check-in`, { latitude: Number(lat), longitude: Number(lon), accuracy_m: acc ? Number(acc) : null, claimed_at: new Date().toISOString() }, { idempotencyKey: checkinKey.current, expectedRevision: job.state_revision }); }
      await load();
    } catch (error) { setActionError(error); if (error instanceof ApiError && error.status === 409) { (which === "accept" ? acceptKey : checkinKey).current = null; await load(); } }
    finally { setBusy(null); }
  };
  const useMyLocation = () => navigator.geolocation?.getCurrentPosition((p) => { setLat(String(p.coords.latitude)); setLon(String(p.coords.longitude)); setAcc(String(Math.round(p.coords.accuracy))); }, () => setActionError(new Error("Location permission denied; enter coordinates.")));
  const useDispatch = () => { if (job.dispatch_location) { setLat(String(job.dispatch_location.lat)); setLon(String(job.dispatch_location.lon)); setAcc(String(job.dispatch_location.accuracy_m ?? 5)); } };
  const reqs = Object.entries(job.proof_requirements).filter(([, v]) => v).map(([k]) => requirementLabel(k));
  return (
    <div className="page crew-job">
      <PageHeader eyebrow={`Job ${job.id}`} title={job.location} meta={<><StatusBadge label={st.label} tone={st.tone} /><Money cents={job.price_cents} simulated /><span>Policy {job.policy_version}</span></>} />
      {state.status === "error" && <ErrorNotice error={state.error} title="Refresh failed, showing the last loaded job" onRetry={() => void load()} />}
      <SectionCard id="job" title="Work order">
        <KeyValue items={[{ label: "Scope", value: job.scope }, { label: "Work area", value: job.work_area }, { label: "Primary target", value: job.primary_target ?? "Unknown" },
          { label: "Equipment", value: job.required_equipment.join(", ") || "None" }, { label: "Crew", value: job.crew_count }, { label: "Required proof", value: <ul className="reqs">{reqs.map((r) => <li key={r}>{r}</li>)}</ul> }]} />
      </SectionCard>
      {pendingException && <Notice tone="warning" title="Awaiting operator decision">A completion exception is pending. New proof is not accepted until the operator decides.</Notice>}
      {actionError ? <ErrorNotice error={actionError} title="Action not saved" /> : null}
      <ol className="steps">
        <li className={`step ${accepted ? "step--done" : "step--current"}`}><SectionCard id="accept" title="1. Accept">
          {accepted ? <p><StatusBadge label="Accepted" tone="resolved" /> <Timestamp value={job.accepted_at} /></p> : <ActionButton onClick={() => void act("accept")} pending={busy === "accept"}>Accept job</ActionButton>}
        </SectionCard></li>
        <li className={`step ${checkedIn ? "step--done" : accepted ? "step--current" : "step--locked"}`}><SectionCard id="checkin" title="2. Check in">
          {checkedIn ? <p><StatusBadge label="Checked in" tone="resolved" /> <Timestamp value={job.checked_in_at} /></p> : accepted ? (
            <div className="stack-3">
              <div className="row"><ActionButton variant="secondary" onClick={useMyLocation}>Use my location</ActionButton>{job.dispatch_location && <ActionButton variant="secondary" onClick={useDispatch}>Use dispatch coordinates, demo</ActionButton>}</div>
              <div className="coords">
                <div className="field"><label htmlFor="lat">Latitude</label><input id="lat" type="number" step="any" value={lat} onChange={(e) => setLat(e.target.value)} /></div>
                <div className="field"><label htmlFor="lon">Longitude</label><input id="lon" type="number" step="any" value={lon} onChange={(e) => setLon(e.target.value)} /></div>
                <div className="field"><label htmlFor="acc">Accuracy (m)</label><input id="acc" type="number" step="any" value={acc} onChange={(e) => setAcc(e.target.value)} /></div>
              </div>
              <p className="small muted">Check-in is a claimed location recorded on the job. Dispatch coordinates are a demo convenience and are labeled as such.</p>
              <ActionButton onClick={() => void act("checkin")} pending={busy === "checkin"}>Check in</ActionButton>
            </div>) : <p className="muted">Accept the job first.</p>}
        </SectionCard></li>
        <li className={`step ${proofOpen ? "step--current" : job.submitted_at ? "step--done" : "step--locked"}`}><SectionCard id="proof" title="3. Proof">
          {job.rework_instructions && <Notice tone="warning" title="Rework required"><p>{job.rework_instructions}</p></Notice>}
          {proofOpen ? <ProofForm key={proofCycleKey} job={job} onSubmitted={() => { setSubmittedLocally(true); void load(); }} /> : job.submitted_at ? <p><StatusBadge label="Submitted" tone="active" /> <Timestamp value={job.submitted_at} /></p> : <p className="muted">Check in first.</p>}
        </SectionCard></li>
        <li className="step"><SectionCard id="result" title="4. Result">
          <p><StatusBadge label={st.label} tone={st.tone} />{job.latest_submission_id && <span className="small muted"> latest submission {job.latest_submission_id}</span>}</p>
          {job.status === "PAID" && <p className="small">Settlement was simulated for <Money cents={job.price_cents} simulated />.</p>}
        </SectionCard></li>
      </ol>
    </div>
  );
}
