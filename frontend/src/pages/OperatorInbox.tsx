import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import "./OperatorInbox.css";
import { ApiError, read } from "../api/client";
import { exceptionKind, exceptionStatus, requirementLabel } from "../api/labels";
import { loadSession } from "../api/session";
import { ExceptionDetailPanel } from "../components/ExceptionDetail";
import { PageHeader } from "../components/PageHeader";
import { Points } from "../components/Points";
import { RequirePersona } from "../components/RequirePersona";
import { EmptyState, ErrorNotice, PendingState } from "../components/States";
import { StatusBadge } from "../components/StatusBadge";
import type { ExceptionDetail, ExceptionListPage } from "../types";

export function OperatorInbox() {
  // RequirePersona only gates on session state; the shared session store is
  // otherwise bootstrapped by App.tsx. When this page renders standalone
  // (e.g. in tests) nothing else triggers the initial load, so do it here too
  // - loadSession() is idempotent to call more than once.
  useEffect(() => { void loadSession(); }, []);
  return <RequirePersona allow={["operator"]}><InboxContent /></RequirePersona>;
}

function Row({ ex, selected }: { ex: ExceptionDetail; selected: boolean }) {
  const st = exceptionStatus(ex.status);
  return (
    <li className={`inbox-row ${selected ? "inbox-row--selected" : ""}`}>
      <Link to={`/inbox?exception=${ex.id}`} className="inbox-row__link" aria-current={selected ? "true" : undefined}>
        <div className="row"><StatusBadge label={st.label} tone={st.tone} /><span className="small muted">{exceptionKind(ex.kind)}</span></div>
        <p className="inbox-row__title">{ex.scope}</p>
        <p className="small muted">{ex.issue_id}{ex.job_id ? `, job ${ex.job_id}` : ""}. {requirementLabel(ex.reason_code)}{ex.total !== null && ex.total !== undefined ? <>. <Points value={ex.total} threshold={ex.payment_threshold} style="of" /></> : null}</p>
      </Link>
    </li>
  );
}

function InboxContent() {
  const [params] = useSearchParams(); const selected = params.get("exception");
  const [list, setList] = useState<{ status: "pending" | "ready" | "error"; data: ExceptionListPage | null; error: unknown }>({ status: "pending", data: null, error: null });
  const load = useCallback(async () => {
    try {
      // The default list only returns PENDING and DECIDED items; fetch HANDLED
      // and CANCELLED separately so the "Decided and handled" group is complete.
      const [base, handled, cancelled] = await Promise.all([
        read<ExceptionListPage>("/api/exceptions?limit=50"),
        read<ExceptionListPage>("/api/exceptions?status=HANDLED&limit=50"),
        read<ExceptionListPage>("/api/exceptions?status=CANCELLED&limit=50"),
      ]);
      const merged = new Map<string, ExceptionDetail>();
      for (const e of [...base.exceptions, ...handled.exceptions, ...cancelled.exceptions]) merged.set(e.id, e);
      setList({ status: "ready", data: { ...base, exceptions: Array.from(merged.values()) }, error: null });
    } catch (error) { setList((s) => ({ status: "error", data: s.data, error: error instanceof ApiError ? error : new Error(String(error)) })); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const data = list.data;
  const pending = data?.exceptions.filter((e) => e.status === "PENDING") ?? [];
  const others = data?.exceptions.filter((e) => e.status !== "PENDING") ?? [];
  return (
    <div className={`page inbox ${selected ? "inbox--detail" : ""}`}>
      <PageHeader eyebrow="Operator" title="Operator inbox" meta={data && <span>{data.pending_count} pending, {data.decided_count} decided</span>} />
      {list.status === "error" && <ErrorNotice error={list.error} onRetry={() => void load()} />}
      <div className="inbox__grid">
        <section className="inbox__list" aria-label="Exceptions">
          {list.status === "pending" && !data ? <PendingState /> : pending.length === 0 ? <EmptyState title="No decisions waiting">Pending exceptions appear here with the one permitted action.</EmptyState> : (
            <ul className="inbox-list">{pending.map((e) => <Row key={e.id} ex={e} selected={e.id === selected} />)}</ul>
          )}
          {others.length > 0 && (
            <details className="inbox__decided"><summary>Decided and handled ({others.length})</summary>
              <ul className="inbox-list">{others.map((e) => <Row key={e.id} ex={e} selected={e.id === selected} />)}</ul></details>
          )}
        </section>
        <section className="inbox__detail" aria-label="Exception detail">
          {selected ? (<>
            <Link to="/inbox" className="inbox__back small">Back to inbox</Link>
            <ExceptionDetailPanel key={selected} exceptionId={selected} onChanged={() => void load()} />
          </>) : <p className="muted">Select an exception to see the failed requirement and the permitted action.</p>}
        </section>
      </div>
    </div>
  );
}
