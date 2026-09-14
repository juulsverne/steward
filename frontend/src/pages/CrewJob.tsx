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
  const { jobId = "" } = useParams();
  return <RequirePersona allow={["crew"]}><JobContent key={jobId} /></RequirePersona>;
}

function JobContent() {
  const { jobId = "" } = useParams();
  const [state, setState] = useState<{ status: "pending" | "ready" | "error"; data: CrewJobView | null; error: unknown }>({ status: "pending", data: null, error: null });
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await read<CrewJobView>(`/api/jobs/${encodeURIComponent(jobId)}`, { signal });
      if (!signal?.aborted) setState({ status: "ready", data, error: null });
    } catch (error) {
      if (!signal?.aborted) setState((s) => ({ status: "error", data: s.data, error: error instanceof ApiError ? error : new Error(String(error)) }));
    }
  }, [jobId]);
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);
  const [busy, setBusy] = useState<"accept" | "checkin" | null>(null); const [actionError, setActionError] = useState<unknown>(null);
  const acceptKey = useRef<string | null>(null); const checkinAttempt = useRef<{ key: string; body: { latitude: number; longitude: number; accuracy_m: number | null; claimed_at: string }; expectedRevision: number } | null>(null); const locationRequest = useRef(0);
  const [lat, setLat] = useState(""); const [lon, setLon] = useState(""); const [acc, setAcc] = useState("");
  const [pendingException, setPendingException] = useState(false);
  useEffect(() => {
    if (!jobId) return;
    const controller = new AbortController();
    read<{ jobs: Array<{ id: string; pending_exception_status: string | null }> }>("/api/crew/jobs?limit=50", { signal: controller.signal })
      .then((v) => { if (!controller.signal.aborted) setPendingException(v.jobs.find((j) => j.id === jobId)?.pending_exception_status === "PENDING"); })
      .catch(() => { if (!controller.signal.aborted) setPendingException(false); });
    return () => controller.abort();
  }, [jobId, state.data?.state_revision]);
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
      else {
        locationRequest.current += 1;
        checkinAttempt.current ??= { key: newIdempotencyKey("checkin"), expectedRevision: job.state_revision, body: { latitude: Number(lat), longitude: Number(lon), accuracy_m: acc ? Number(acc) : null, claimed_at: new Date().toISOString() } };
        const attempt = checkinAttempt.current;
        await mutate<EntityResult>(`/api/jobs/${encodeURIComponent(job.id)}/check-in`, attempt.body, { idempotencyKey: attempt.key, expectedRevision: attempt.expectedRevision });
      }
      await load();
    } catch (error) { setActionError(error); if (error instanceof ApiError && error.status === 409) { if (which === "accept") acceptKey.current = null; else checkinAttempt.current = null; await load(); } }
    finally { setBusy(null); }
  };
  const discardCheckinAttempt = () => { locationRequest.current += 1; checkinAttempt.current = null; };
  const useMyLocation = () => {
    // Choosing a new device location is an edit after a failed attempt, so it
    // must intentionally start a fresh payload/key rather than retain stale
    // coordinates or leave the helper inert.
    discardCheckinAttempt();
    const request = ++locationRequest.current;
    navigator.geolocation?.getCurrentPosition((p) => {
      if (request !== locationRequest.current || checkinAttempt.current) return;
      setLat(String(p.coords.latitude)); setLon(String(p.coords.longitude)); setAcc(String(Math.round(p.coords.accuracy)));
    }, () => { if (request === locationRequest.current && !checkinAttempt.current) setActionError(new Error("Location permission denied; enter coordinates.")); });
  };
  const useDispatch = () => { if (job.dispatch_location) { discardCheckinAttempt(); setLat(String(job.dispatch_location.lat)); setLon(String(job.dispatch_location.lon)); setAcc(String(job.dispatch_location.accuracy_m ?? 5)); } };
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
          {accepted ? <p><StatusBadge label="Accepted" tone="active" /> <Timestamp value={job.accepted_at} /></p> : <ActionButton onClick={() => void act("accept")} pending={busy === "accept"}>Accept job</ActionButton>}
        </SectionCard></li>
        <li className={`step ${checkedIn ? "step--done" : accepted ? "step--current" : "step--locked"}`}><SectionCard id="checkin" title="2. Check in">
          {checkedIn ? <p><StatusBadge label="Checked in" tone="active" /> <Timestamp value={job.checked_in_at} /></p> : accepted ? (
            <div className="stack-3">
              <div className="row"><ActionButton variant="secondary" onClick={useMyLocation} disabled={busy === "checkin"}>Use my location</ActionButton>{job.dispatch_location && <ActionButton variant="secondary" onClick={useDispatch} disabled={busy === "checkin"}>Use dispatch coordinates, demo</ActionButton>}</div>
              <div className="coords">
                <div className="field"><label htmlFor="lat">Latitude</label><input id="lat" type="number" step="any" value={lat} onChange={(e) => { discardCheckinAttempt(); setLat(e.target.value); }} disabled={busy === "checkin"} /></div>
                <div className="field"><label htmlFor="lon">Longitude</label><input id="lon" type="number" step="any" value={lon} onChange={(e) => { discardCheckinAttempt(); setLon(e.target.value); }} disabled={busy === "checkin"} /></div>
                <div className="field"><label htmlFor="acc">Accuracy (m)</label><input id="acc" type="number" step="any" value={acc} onChange={(e) => { discardCheckinAttempt(); setAcc(e.target.value); }} disabled={busy === "checkin"} /></div>
              </div>
              <p className="small muted">Check-in is a claimed location recorded on the job. Dispatch coordinates are a demo convenience and are labeled as such.</p>
              <ActionButton onClick={() => void act("checkin")} pending={busy === "checkin"}>Check in</ActionButton>
            </div>) : <p className="muted">Accept the job first.</p>}
        </SectionCard></li>
        <li className={`step ${proofOpen ? "step--current" : job.submitted_at ? "step--done" : "step--locked"}`}><SectionCard id="proof" title="3. Proof">
          {job.rework_instructions && job.status === "REWORK_REQUIRED" && <Notice tone="warning" title="Rework required"><p>{job.rework_instructions}</p></Notice>}
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
