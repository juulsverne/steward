import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import "./OperationsBoard.css";
import { ApiError, read } from "../api/client";
import { issueStatus, markerTone } from "../api/labels";
import { IssueMap } from "../components/IssueMap";
import { Money } from "../components/Money";
import { PageHeader } from "../components/PageHeader";
import { ProvenanceTag } from "../components/ProvenanceTag";
import { RequirePersona } from "../components/RequirePersona";
import { ActionButton } from "../components/ActionButton";
import { EmptyState, ErrorNotice, PendingState } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import { Timestamp } from "../components/Timestamp";
import { money, relativeAsOf } from "../lib/format";
import type { BoardMarker, BoardView } from "../types";

const ORDER: Record<string, number> = { attention: 0, active: 1, watching: 2, resolved: 3 };

function useBoard() {
  const [state, setState] = useState<{ status: "pending" | "ready" | "error"; data: BoardView | null; error: unknown; asOf: string | null }>({ status: "pending", data: null, error: null, asOf: null });
  const load = useCallback(async () => {
    try { const data = await read<BoardView>("/api/board?limit=50"); setState({ status: "ready", data, error: null, asOf: new Date().toISOString() }); }
    catch (error) { setState((s) => ({ status: "error", data: s.data, error: error instanceof ApiError ? error : new Error(String(error)), asOf: s.asOf })); }
  }, []);
  useEffect(() => { void load(); const id = setInterval(() => { if (document.visibilityState === "visible") void load(); }, 20000); return () => clearInterval(id); }, [load]);
  return { ...state, reload: load };
}

function Tile({ label, value, caption }: { label: string; value: React.ReactNode; caption?: string }) {
  return <div className="tile"><p className="tile__value">{value}</p><p className="tile__label">{label}</p>{caption && <p className="tile__caption muted small">{caption}</p>}</div>;
}

function MarkerRow({ k, selected, onSelect }: { k: BoardMarker; selected: boolean; onSelect: (id: string) => void }) {
  const status = issueStatus(k.status);
  return (
    <li className={`issue-row ${selected ? "issue-row--selected" : ""}`} onMouseEnter={() => onSelect(k.issue_id)}>
      <StatusBadge label={status.label} tone={markerTone(k.marker_state)} />
      <div className="issue-row__text">
        <Link to={`/issues/${k.issue_id}`} className="issue-row__link">{k.label}</Link>
        <p className="small muted">
          {k.current_job_id && <span>Job in progress. </span>}
          {k.payment_id && <span>Paid, simulated. </span>}
          {k.location_provenance && <ProvenanceTag provenance={k.location_provenance} />}
        </p>
      </div>
    </li>
  );
}

export function OperationsBoard() {
  return <RequirePersona allow={["operator"]}><BoardContent /></RequirePersona>;
}

function BoardContent() {
  const { status, data, error, asOf, reload } = useBoard();
  const [selected, setSelected] = useState<string | null>(null);
  if (status === "pending" && !data) return <div className="page"><PageHeader eyebrow="Operations board" title="South Loop Demo District" /><PendingState /></div>;
  if (!data) return <div className="page"><PageHeader eyebrow="Operations board" title="South Loop Demo District" /><ErrorNotice error={error} onRetry={() => void reload()} /></div>;
  const markers = Array.isArray(data.markers) ? data.markers : [];
  const located = [...markers].sort((a, b) => ORDER[a.marker_state] - ORDER[b.marker_state]).filter((k) => k.latitude !== null);
  const unlocated = markers.filter((k) => k.latitude === null);
  const b = data.budget; const total = Math.max(b.initial_cents, 1);
  return (
    <div className="page board">
      <PageHeader eyebrow="Operations board" title="South Loop Demo District"
        meta={<><span>Policy {data.policy_version}</span><Timestamp value={data.as_of} label="as of" /></>}
        actions={<ActionButton variant="secondary" onClick={() => void reload()}>Refresh</ActionButton>} />
      {status === "error" && <ErrorNotice error={error} title={`Refresh failed, showing data ${asOf ? relativeAsOf(asOf) : ""}`} onRetry={() => void reload()} />}
      <section className="tiles" aria-label="Summary">
        <Tile label="Attention" value={data.counts.attention === 0 ? <span className="tile__quiet">No decisions waiting</span> : data.counts.attention} caption="pending operator decisions, not a lifecycle bucket" />
        <Tile label="Watching" value={data.counts.watching} caption="watching, not yet actionable" />
        <Tile label="Active" value={data.counts.active} caption="being handled" />
        <Tile label="Resolved" value={data.counts.resolved} caption="closed with accepted proof" />
        <div className="tile tile--budget">
          <p className="tile__value"><Money cents={b.available_cents} /></p>
          <p className="tile__label">Budget available</p>
          <div className="budget-bar" role="img" aria-label={`${money(b.available_cents)} available, ${money(b.reserved_cents)} reserved, ${money(b.spent_cents)} spent`}>
            <span className="budget-bar__available" style={{ width: `${(b.available_cents / total) * 100}%` }} />
            <span className="budget-bar__reserved" style={{ width: `${(b.reserved_cents / total) * 100}%` }} />
            <span className="budget-bar__spent" style={{ width: `${(b.spent_cents / total) * 100}%` }} />
          </div>
          <p className="small muted tabular">{money(b.reserved_cents)} reserved, {money(b.spent_cents)} spent of {money(b.initial_cents)}</p>
        </div>
      </section>
      <div className="board__grid">
        <section className="board__list" aria-label="Issues">
          {markers.length === 0 ? <EmptyState title="No issues in this district" /> : (
            <>
              <ul className="issue-list">{located.map((k) => <MarkerRow key={k.issue_id} k={k} selected={k.issue_id === selected} onSelect={setSelected} />)}</ul>
              {unlocated.length > 0 && (
                <div className="stack-2">
                  <h3>Location not resolved</h3>
                  <ul className="issue-list">{unlocated.map((k) => (
                    <li key={k.issue_id} className="issue-row">
                      <StatusBadge label={issueStatus(k.status).label} tone={markerTone(k.marker_state)} />
                      <div className="issue-row__text"><Link to={`/issues/${k.issue_id}`} className="issue-row__link">{k.label}</Link><p className="small muted">{k.location_unknown_reason ?? "No coordinates saved"}</p></div>
                    </li>))}</ul>
                </div>
              )}
            </>
          )}
        </section>
        <aside className="board__map"><IssueMap markers={markers} selectedId={selected} onSelect={setSelected} /></aside>
      </div>
    </div>
  );
}
