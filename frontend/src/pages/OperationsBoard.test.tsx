import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadSession, resetSessionForTests } from "../api/session";
import { OperationsBoard } from "./OperationsBoard";

vi.mock("../components/IssueMap", () => ({ IssueMap: () => <div data-testid="map" /> }));

const board = {
  as_of: "2026-09-14T15:00:00Z", district_id: "south_loop_demo", policy_version: "v3",
  counts: { watching: 1, active: 0, resolved: 1, attention: 0 },
  budget: { budget_id: "b", initial_cents: 50000, reserved_cents: 0, spent_cents: 7200, available_cents: 42800 },
  markers: [
    { issue_id: "demo-couch", status: "RESOLVED", marker_state: "resolved", latitude: 41.86, longitude: -87.62, accuracy_m: 5, location_provenance: "seeded", location_unknown_reason: null, label: "Couch at 1200 S Wabash", current_job_id: null, payment_id: "pay-1", simulated: true },
    { issue_id: "iss-2", status: "CANDIDATE", marker_state: "watching", latitude: null, longitude: null, accuracy_m: null, location_provenance: null, location_unknown_reason: "address not in seeded set", label: "Mattress near 9th", current_job_id: null, payment_id: null, simulated: null },
  ],
};
const envelope = (data: unknown) => new Response(JSON.stringify({ outcome: "OK", reason_code: null, data, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [] }), { status: 200, headers: { "content-type": "application/json" } });

// The RequirePersona wrapper reads global session state via useSession(); in the real app App.tsx
// loads it once on mount. This test renders OperationsBoard standalone, so we drive the session
// store directly with loadSession() (same pattern as api/session.test.tsx) before asserting.
beforeEach(async () => {
  resetSessionForTests();
  vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
    Promise.resolve(String(input).startsWith("/api/board") ? envelope(board)
      : envelope({ sandbox: true, notice: "", actor: { actor_id: "o", actor_type: "operator", label: "District operator (seeded)" }, personas: [] })));
  await loadSession();
});
afterEach(() => vi.restoreAllMocks());

describe("OperationsBoard", () => {
  it("shows counts, budget arithmetic, and No decisions waiting for zero attention", async () => {
    render(<MemoryRouter><OperationsBoard /></MemoryRouter>);
    expect(await screen.findByText("No decisions waiting")).toBeInTheDocument();
    expect(screen.getByText("$428.00")).toBeInTheDocument();
    expect(screen.getByText(/\$72\.00 spent/)).toBeInTheDocument();
    expect(screen.getByText(/\$0\.00 reserved/)).toBeInTheDocument();
  });
  it("lists every marker as a link and groups unlocated ones with the reason", async () => {
    render(<MemoryRouter><OperationsBoard /></MemoryRouter>);
    expect(await screen.findByRole("link", { name: /Couch at 1200 S Wabash/ })).toHaveAttribute("href", "/issues/demo-couch");
    expect(screen.getByText("Location not resolved")).toBeInTheDocument();
    expect(screen.getByText(/address not in seeded set/)).toBeInTheDocument();
    expect(screen.getByText("Resolved", { selector: "span.badge--resolved" })).toHaveClass("badge--resolved");
    expect(screen.getByText(/Paid, simulated/)).toBeInTheDocument();
  });
});
