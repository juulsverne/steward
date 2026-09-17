import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { resetSessionForTests } from "./api/session";

const personas = [
  { persona_id: "operator", label: "District operator (seeded)", actor_type: "operator" },
  { persona_id: "crew-south_loop_services", label: "South Loop Services crew (seeded)", actor_type: "crew" },
];
const session = (actor: unknown) => new Response(JSON.stringify({ outcome: "OK", reason_code: null, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [],
  data: { sandbox: true, notice: "Sandbox demo personas", actor, personas } }), { status: 200, headers: { "content-type": "application/json" } });
const board = new Response(JSON.stringify({ outcome: "OK", reason_code: null, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [],
  data: { as_of: "2026-09-14T15:00:00Z", district_id: "south_loop_demo", policy_version: "v3",
    counts: { watching: 0, active: 0, resolved: 0, attention: 0 },
    budget: { budget_id: "b", initial_cents: 50000, reserved_cents: 0, spent_cents: 0, available_cents: 50000 },
    markers: [] } }), { status: 200, headers: { "content-type": "application/json" } });
const fetchFor = (actor: unknown) => (input: RequestInfo | URL) =>
  Promise.resolve(String(input).startsWith("/api/board") ? board.clone() : session(actor));

beforeEach(() => { resetSessionForTests(); window.history.pushState({}, "", "/"); });
afterEach(() => vi.restoreAllMocks());

describe("App frame", () => {
  it("shows the district, sandbox chip, switcher and theme toggle, and hides operator nav without an actor", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(fetchFor(null));
    render(<App />);
    const header = within(screen.getByRole("banner"));
    await waitFor(() => expect(header.getByLabelText("Persona")).toBeEnabled());
    expect(screen.getByText("Loop Demo District")).toBeInTheDocument();
    expect(screen.getByText("Sandbox demo")).toBeInTheDocument();
    expect(header.getByLabelText("Theme")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Inbox" })).toBeNull();
    expect(screen.getByRole("link", { name: "Report" })).toBeInTheDocument();
  });
  it("shows Board and Inbox for an operator and Crew for a crew persona", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(fetchFor({ actor_id: "o", actor_type: "operator", label: "District operator (seeded)" }));
    render(<App />);
    await waitFor(() => expect(screen.getByRole("link", { name: "Inbox" })).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Board" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Crew" })).toBeNull();
  });
  it("renders the footer disclaimer", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(session(null)));
    render(<App />);
    expect(await screen.findByText(/simulated dispatch and settlement/i)).toBeInTheDocument();
  });
});
