import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { ApiError, read } from "../api/client";
import { jobStatus } from "../api/labels";
import { loadSession } from "../api/session";
import { Money } from "../components/Money";
import { PageHeader } from "../components/PageHeader";
import { RequirePersona } from "../components/RequirePersona";
import { EmptyState, ErrorNotice, PendingState } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import "./CrewJobs.css";
import type { CrewJobListView } from "../types";

export function CrewJobs() {
  // See CrewJob.tsx: bootstraps the session for a page mounted without App.tsx's effect.
  useEffect(() => { void loadSession(); }, []);
  return <RequirePersona allow={["crew"]}><JobsContent /></RequirePersona>;
}

function JobsContent() {
  const [state, setState] = useState<{ status: "pending" | "ready" | "error"; data: CrewJobListView | null; error: unknown }>({ status: "pending", data: null, error: null });
  const load = useCallback(async () => {
    try { setState({ status: "ready", data: await read<CrewJobListView>("/api/crew/jobs?limit=50"), error: null }); }
    catch (error) { setState((s) => ({ status: "error", data: s.data, error: error instanceof ApiError ? error : new Error(String(error)) })); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  return (
    <div className="page crew-list">
      <PageHeader eyebrow="Crew" title="Your jobs" />
      {state.status === "pending" && !state.data ? <PendingState /> : state.status === "error" && !state.data ? <ErrorNotice error={state.error} onRetry={() => void load()} /> :
        (state.data?.jobs.length ?? 0) === 0 ? <EmptyState title="No jobs assigned to this vendor" /> : (
          <ul className="job-cards">{state.data!.jobs.map((j) => { const st = jobStatus(j.status); return (
            <li key={j.id} className="job-card">
              <div className="job-card__body stack-2">
                <div className="row"><StatusBadge label={st.label} tone={st.tone} />{j.pending_exception_status === "PENDING" && <StatusBadge label="Awaiting operator decision" tone="attention" />}</div>
                <p><Link to={`/crew/jobs/${j.id}`} className="job-card__link">{j.location}</Link></p>
                <p className="small muted">{j.scope}. <Money cents={j.price_cents} simulated /></p>
              </div>
            </li>); })}</ul>
        )}
    </div>
  );
}
