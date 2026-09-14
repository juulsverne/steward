import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { resetSessionForTests } from "./api/session";

const personas = [
  { persona_id: "operator", label: "District operator (seeded)", actor_type: "operator" },
  { persona_id: "crew-south_loop_services", label: "South Loop Services crew (seeded)", actor_type: "crew" },
];
const session = (actor: unknown) => new Response(JSON.stringify({ outcome: "OK", reason_code: null, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [],
  data: { sandbox: true, notice: "Sandbox demo personas", actor, personas } }), { status: 200, headers: { "content-type": "application/json" } });

beforeEach(() => { resetSessionForTests(); window.history.pushState({}, "", "/"); });
afterEach(() => vi.restoreAllMocks());

describe("App frame", () => {
  it("shows the district, sandbox chip, switcher and theme toggle, and hides operator nav without an actor", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(session(null)));
    render(<App />);
    await waitFor(() => expect(screen.getByLabelText("Persona")).toBeEnabled());
    expect(screen.getByText("South Loop Demo District")).toBeInTheDocument();
    expect(screen.getByText("Sandbox demo")).toBeInTheDocument();
    expect(screen.getByLabelText("Theme")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Inbox" })).toBeNull();
    expect(screen.getByRole("link", { name: "Report" })).toBeInTheDocument();
  });
  it("shows Board and Inbox for an operator and Crew for a crew persona", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(session({ actor_id: "o", actor_type: "operator", label: "District operator (seeded)" })));
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
