import type { ReactNode } from "react";
import { ApiError, reasonText } from "../api/client";
import { invocationGloss } from "../api/labels";
import type { InvocationStatus } from "../types";
import { ActionButton } from "./ActionButton";
import { Notice } from "./Notice";
import { StatusBadge } from "./StatusBadge";

export function PendingState({ label = "Loading" }: { label?: string }) {
  return <p className="pending muted" role="status" aria-live="polite">{label}</p>;
}
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><p className="empty__title">{title}</p>{children && <div className="muted small">{children}</div>}</div>;
}
export function ErrorNotice({ error, onRetry, title = "Could not load" }: { error: unknown; onRetry?: () => void; title?: string }) {
  const text = error instanceof ApiError ? reasonText(error.reasonCode) : error instanceof Error ? error.message : "Unknown error";
  return (
    <Notice tone="error" title={title}>
      <p>{text}{error instanceof ApiError && error.status ? ` (HTTP ${error.status})` : ""}</p>
      {onRetry && <ActionButton variant="secondary" onClick={onRetry}>Retry</ActionButton>}
    </Notice>
  );
}
export function SavedState({ phase, status, detail, onRefresh }: { phase: "saved" | "processing" | "exhausted"; status?: InvocationStatus | null; detail?: ReactNode; onRefresh?: () => void }) {
  const gloss = status ? invocationGloss(status) : null;
  return (
    <div className="saved-state" role="status" aria-live="polite">
      <div className="row">
        {phase === "saved" && <StatusBadge label="Saved" tone="resolved" />}
        {gloss && <><StatusBadge label={gloss.label} tone={gloss.tone} /><span className="muted small">{gloss.gloss}</span></>}
      </div>
      {detail && <div className="small">{detail}</div>}
      {phase === "exhausted" && <p className="small">Processing is still saved on the server. <ActionButton variant="quiet" onClick={onRefresh}>Refresh</ActionButton></p>}
    </div>
  );
}
