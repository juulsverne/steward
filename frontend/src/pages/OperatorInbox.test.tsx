import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetSessionForTests } from "../api/session";
import { OperatorInbox } from "./OperatorInbox";

const pending = { id: "exc-1", issue_id: "demo-couch", job_id: "job-1", submission_id: "sub-1", verification_id: "ver-1", kind: "completion", reason_code: "SCORE_BELOW_THRESHOLD", status: "PENDING", state_revision: 3, job_revision: 5,
  scope: "Remove couch and debris", primary_target: "couch", work_area: "parkway", before_evidence_id: "ev-b", after_evidence_id: "ev-a1", denial_event_id: 20,
  components: { gps_within_30m: 30, after_later_than_before: 10, target_removed: 40, no_new_hazard: 10, area_clear: 0 }, total: 90, findings: null, checks: null,
  prerequisites: [{ name: "same_scene", allowed: true, unmet: [] }], score_gate: { name: "verification_score", allowed: false, unmet: ["area_clear"] }, payment_threshold: 95,
  unmet: ["area_clear"], allowed_next: ["request_completion"], decision_id: null, invocation_id: null, invocation_status: null, handled_at: null, cancelled_at: null, cancellation_event_id: null };
const decided = { ...pending, id: "exc-0", status: "HANDLED", allowed_next: [], unmet: [] };
const envelope = (data: unknown, status = 200) => new Response(JSON.stringify({ outcome: "OK", reason_code: null, data, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [7] }), { status, headers: { "content-type": "application/json" } });
const denied = () => new Response(JSON.stringify({ outcome: "DENIED", reason_code: "REVISION_CONFLICT", data: null, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [] }), { status: 409, headers: { "content-type": "application/json" } });

let conflict = false; let posted: Request[] = [];
beforeEach(() => { resetSessionForTests(); conflict = false; posted = []; vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
  const url = String(input);
  if (init?.method === "POST" && url.includes("request-completion")) { posted.push(new Request(new URL(url, "http://localhost"), init)); return Promise.resolve(conflict ? denied() : envelope({ record_id: "exc-1", state_revision: 4, invocation_id: "inv-9" }, 202)); }
  if (url.startsWith("/api/exceptions/exc-1")) return Promise.resolve(envelope(pending));
  if (url.startsWith("/api/exceptions/exc-0")) return Promise.resolve(envelope(decided));
  if (url.startsWith("/api/exceptions")) return Promise.resolve(envelope({ exceptions: [pending, decided], pending_count: 1, decided_count: 1 }));
  if (url.startsWith("/api/invocations/")) return Promise.resolve(envelope({ invocation_id: "inv-9", trigger_event_id: 7, status: "WAITING", state_revision: 4, episode_count: 1, model_cycles: 1, tool_requests: 1, logical_requests: 1, transport_attempts: 1, error_code: null, trace: [] }));
  return Promise.resolve(envelope({ sandbox: true, notice: "", actor: { actor_id: "o", actor_type: "operator", label: "District operator (seeded)" }, personas: [] }));
}); });
afterEach(() => vi.restoreAllMocks());

const mount = (path = "/inbox?exception=exc-1") => render(<MemoryRouter initialEntries={[path]}><OperatorInbox /></MemoryRouter>);

describe("OperatorInbox", () => {
  it("lists pending first and shows the failed requirement, score and one action", async () => {
    mount();
    expect(await screen.findByText("1 pending, 1 decided")).toBeInTheDocument();
    expect(await screen.findByText(/Failed: Area clear/)).toBeInTheDocument();
    expect(screen.getByText("90 of 95 for payment")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Request completion" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /pay|approve|close/i })).toBeNull();
  });
  it("sends the request with the expected revision, then shows saved and resumed processing separately", async () => {
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Request completion" }));
    expect(await screen.findByText("Decision saved")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("WAITING")).toBeInTheDocument());
    expect(screen.getByText(/Processing resumed/)).toBeInTheDocument();
    expect(posted[0].headers.get("X-Steward-Expected-Revision")).toBe("3");
    expect(await posted[0].json()).toEqual({ submission_id: "sub-1", expected_job_revision: 5 });
    expect(screen.getByRole("button", { name: "Request completion" })).toBeDisabled();
  });
  it("explains a stale item on 409 and refreshes", async () => {
    conflict = true; mount();
    await userEvent.click(await screen.findByRole("button", { name: "Request completion" }));
    expect(await screen.findByText(/changed since you opened it/)).toBeInTheDocument();
  });
  it("offers no action on a handled exception", async () => {
    mount("/inbox?exception=exc-0");
    expect((await screen.findAllByText("Handled"))[0]).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request completion" })).toBeNull();
  });
});
