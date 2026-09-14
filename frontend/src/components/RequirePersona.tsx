import type { ReactNode } from "react";
import { actorType, loadSession, useSession, verifiedActorIdentity } from "../api/session";
import { ErrorNotice } from "./States";
import type { ActorType } from "../types";
import { Notice } from "./Notice";
import { PersonaSwitcher } from "./PersonaSwitcher";

const NAMES: Record<ActorType, string> = { operator: "the District operator", crew: "a crew", resident: "a resident", service: "Steward" };

export function RequirePersona({ allow, children }: { allow: ActorType[]; children: ReactNode }) {
  const s = useSession();
  const type = actorType(s);
  if (s.status === "loading") return <p className="muted">Loading session</p>;
  if (s.switching) return <p className="muted" role="status">Changing persona</p>;
  if (s.status === "error") return <ErrorNotice error={s.error} title="Session unavailable" onRetry={() => void loadSession()} />;
  const identity = verifiedActorIdentity(s);
  if (identity && type && allow.includes(type)) return <div key={identity}>{children}</div>;
  return (
    <Notice tone="info" title={`This page needs ${allow.map((a) => NAMES[a]).join(" or ")} persona`}>
      <p>Select a demo persona to continue. Personas are a labeled sandbox, not sign-in.</p>
      <PersonaSwitcher />
    </Notice>
  );
}
