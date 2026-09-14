import { useSyncExternalStore } from "react";
import type { ActorType, DemoSessionView } from "../types";
import { ApiError, mutate, newIdempotencyKey, read, reasonText } from "./client";

export interface SessionState { status: "loading" | "ready" | "error"; session: DemoSessionView | null; error: ApiError | null; switching: boolean; switchError: string | null }

let state: SessionState = { status: "loading", session: null, error: null, switching: false, switchError: null };
const listeners = new Set<() => void>();
function set(patch: Partial<SessionState>) { state = { ...state, ...patch }; listeners.forEach((l) => l()); }
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

export function useSession(): SessionState { return useSyncExternalStore(subscribe, () => state, () => state); }
export function actorType(s: SessionState): ActorType | null { return (s.session?.actor?.actor_type as ActorType | undefined) ?? null; }
export function resetSessionForTests(): void { state = { status: "loading", session: null, error: null, switching: false, switchError: null }; }

export async function loadSession(): Promise<void> {
  try { const session = await read<DemoSessionView>("/api/demo/session"); set({ status: "ready", session, error: null }); }
  catch (error) { set({ status: "error", error: error instanceof ApiError ? error : new ApiError(0, { reason_code: "NETWORK" }) }); }
}

export async function switchPersona(personaId: string): Promise<boolean> {
  set({ switching: true, switchError: null });
  try {
    await mutate("/api/demo/persona", { persona_id: personaId }, { idempotencyKey: newIdempotencyKey("persona") });
    await loadSession();
    set({ switching: false });
    return true;
  } catch (error) {
    const reason = error instanceof ApiError ? reasonText(error.reasonCode) : "Network error";
    set({ switching: false, switchError: reason });
    return false;
  }
}
