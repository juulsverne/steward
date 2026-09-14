import type { ReactNode } from "react";
import { actorType, useSession } from "../api/session";
import type { ActorType } from "../types";
import { Notice } from "./Notice";
import { PersonaSwitcher } from "./PersonaSwitcher";

const NAMES: Record<ActorType, string> = { operator: "the District operator", crew: "a crew", resident: "a resident", service: "Steward" };

export function RequirePersona({ allow, children }: { allow: ActorType[]; children: ReactNode }) {
  const s = useSession();
  const type = actorType(s);
  if (s.status === "loading") return <p className="muted">Loading session</p>;
  if (type && allow.includes(type)) return <>{children}</>;
  return (
    <Notice tone="info" title={`This page needs ${allow.map((a) => NAMES[a]).join(" or ")} persona`}>
      <p>Select a demo persona to continue. Personas are a labeled sandbox, not sign-in.</p>
      <PersonaSwitcher />
    </Notice>
  );
}
