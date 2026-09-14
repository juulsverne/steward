import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PersonaSwitcher } from "../components/PersonaSwitcher";
import { loadSession, resetSessionForTests, switchPersona, useSession } from "./session";

const personas = [
  { persona_id: "operator", label: "District operator (seeded)", actor_type: "operator" },
  { persona_id: "resident-2", label: "Resident 2 (seeded)", actor_type: "resident" },
];
const view = (actor: unknown) => ({ sandbox: true, notice: "Sandbox", actor, personas });
const envelope = (data: unknown, outcome = "OK", reason_code: string | null = null, status = 200) =>
  new Response(JSON.stringify({ outcome, reason_code, data, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [] }), { status, headers: { "content-type": "application/json" } });

beforeEach(() => resetSessionForTests());
afterEach(() => vi.restoreAllMocks());

function Probe() { const s = useSession(); return <div data-testid="probe">{s.status}:{s.session?.actor ? (s.session.actor as { label: string }).label : "none"}:{s.switchError ?? ""}</div>; }

describe("session", () => {
  it("loads the session and exposes the actor", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(view({ actor_id: "a", actor_type: "operator", label: "District operator (seeded)" })));
    render(<Probe />);
    await act(() => loadSession());
    expect(screen.getByTestId("probe")).toHaveTextContent("ready:District operator (seeded):");
  });

  it("switching posts the persona then re-reads the session", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(envelope(view(null)))
      .mockResolvedValueOnce(envelope(view({ actor_id: "a", actor_type: "operator", label: "District operator (seeded)" })))
      .mockResolvedValueOnce(envelope(view({ actor_id: "a", actor_type: "operator", label: "District operator (seeded)" })));
    render(<><Probe /><PersonaSwitcher /></>);
    await act(() => loadSession());
    await userEvent.selectOptions(screen.getByLabelText("Persona"), "operator");
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("ready:District operator (seeded)"));
    const [, postInit] = fetchMock.mock.calls[1]; const headers = new Headers(postInit!.headers);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/demo/persona");
    expect(headers.get("X-Steward-Request")).toBe("1"); expect(headers.get("Idempotency-Key")).toMatch(/^persona-/);
    expect(fetchMock.mock.calls[2][0]).toBe("/api/demo/session");
  });

  it("keeps the previous selection and shows the reason when switching fails", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(envelope(view({ actor_id: "r", actor_type: "resident", label: "Resident 2 (seeded)" })))
      .mockResolvedValueOnce(envelope(null, "DENIED", "PERSONA_FORBIDDEN", 403));
    render(<><Probe /><PersonaSwitcher /></>);
    await act(() => loadSession());
    const ok = await act(() => switchPersona("operator"));
    expect(ok).toBe(false);
    expect(screen.getByTestId("probe")).toHaveTextContent("ready:Resident 2 (seeded):Persona forbidden");
    expect((screen.getByLabelText("Persona") as HTMLSelectElement).value).toBe("resident-2");
  });

  it("fails closed when the persona mutation succeeds but its session read fails", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(envelope(view({ actor_id: "r", actor_type: "resident", label: "Resident 2 (seeded)" })))
      .mockResolvedValueOnce(envelope(view(null)))
      .mockResolvedValueOnce(envelope(null, "ERROR", "NETWORK", 503));
    render(<><Probe /><PersonaSwitcher /></>);
    await act(() => loadSession());
    await userEvent.selectOptions(screen.getByLabelText("Persona"), "operator");
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("error:none:Network"));
  });
  it("does not let a route session load interrupt an in-progress persona confirmation", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope(view({ actor_id: "r", actor_type: "resident", label: "Resident 2 (seeded)" })));
    render(<Probe />); await act(() => loadSession());
    let resolvePost: ((response: Response) => void) | null = null;
    vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.method === "POST") return new Promise<Response>((resolve) => { resolvePost = resolve; });
      return Promise.resolve(envelope(view({ actor_id: "o", actor_type: "operator", label: "District operator (seeded)" })));
    });
    const switching = switchPersona("operator");
    await act(() => loadSession());
    resolvePost!(envelope(view(null)));
    await act(() => switching);
    expect(screen.getByTestId("probe")).toHaveTextContent("ready:District operator (seeded):");
  });
  it("fails closed when a persona POST has an ambiguous network outcome", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(envelope(view({ actor_id: "r", actor_type: "resident", label: "Resident 2 (seeded)" })))
      .mockRejectedValueOnce(new Error("network down"));
    render(<><Probe /><PersonaSwitcher /></>); await act(() => loadSession());
    await userEvent.selectOptions(screen.getByLabelText("Persona"), "operator");
    await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("error:none:Network"));
  });
});
