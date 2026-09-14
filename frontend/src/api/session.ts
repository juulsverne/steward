import { useSyncExternalStore } from "react";
import type { ActorType, DemoSessionView } from "../types";
import { ApiError, mutate, newIdempotencyKey, read, reasonText } from "./client";

export interface SessionState { status: "loading" | "ready" | "error"; session: DemoSessionView | null; error: ApiError | null; switching: boolean; switchError: string | null }

let state: SessionState = { status: "loading", session: null, error: null, switching: false, switchError: null };
let sessionRequest = 0;
const listeners = new Set<() => void>();
function set(patch: Partial<SessionState>) { state = { ...state, ...patch }; listeners.forEach((l) => l()); }
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

export function useSession(): SessionState { return useSyncExternalStore(subscribe, () => state, () => state); }
export function actorType(s: SessionState): ActorType | null { return (s.session?.actor?.actor_type as ActorType | undefined) ?? null; }
export function verifiedActorIdentity(s: SessionState): string | null {
  const actor = s.session?.actor;
  if (s.status !== "ready" || s.switching || !actor) return null;
  return `${actor.actor_type}:${actor.actor_id}:${actor.vendor_id ?? ""}`;
}
export function resetSessionForTests(): void { sessionRequest += 1; state = { status: "loading", session: null, error: null, switching: false, switchError: null }; }

export async function loadSession(): Promise<void> {
  // A route can mount while the persona POST is awaiting confirmation. That
  // mount must not claim the old session is verified or invalidate the switch.
  if (state.switching) return;
  const request = ++sessionRequest;
  try {
    const session = await read<DemoSessionView>("/api/demo/session");
    if (request === sessionRequest) set({ status: "ready", session, error: null, switching: false });
  } catch (error) {
    if (request === sessionRequest) set({ status: "error", session: null, error: error instanceof ApiError ? error : new ApiError(0, { reason_code: "NETWORK" }), switching: false });
  }
}

export async function switchPersona(personaId: string): Promise<boolean> {
  const request = ++sessionRequest;
  let changed = false;
  set({ switching: true, switchError: null });
  try {
    await mutate("/api/demo/persona", { persona_id: personaId }, { idempotencyKey: newIdempotencyKey("persona") });
    changed = true;
    if (request !== sessionRequest) return false;
    const session = await read<DemoSessionView>("/api/demo/session");
    if (request !== sessionRequest) return false;
    set({ status: "ready", session, error: null, switching: false });
    return true;
  } catch (error) {
    if (request !== sessionRequest) return false;
    const reason = error instanceof ApiError ? reasonText(error.reasonCode) : "Network error";
    if (changed) set({ status: "error", session: null, error: error instanceof ApiError ? error : new ApiError(0, { reason_code: "NETWORK" }), switching: false, switchError: reason });
    else if (!(error instanceof ApiError) || error.status === 0 || error.reasonCode === "INVALID_RESPONSE") set({ status: "error", session: null, error: error instanceof ApiError ? error : new ApiError(0, { reason_code: "NETWORK" }), switching: false, switchError: reason });
    else set({ switching: false, switchError: reason });
    return false;
  }
}
