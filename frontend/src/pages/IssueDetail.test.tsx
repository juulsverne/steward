import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadSession, resetSessionForTests } from "../api/session";
import { IssueDetail } from "./IssueDetail";

const detail = {
  issue: { id: "demo-couch", category: "Discarded couch", location: "1200 S Wabash Ave", status: "RESOLVED", state_revision: 14, evidence_score: 100,
    components: { image: 30, independent_sources: 25, precise_geocode: 10, service_match: 20, persistence: 15 }, responsibility: "district", hazards: [] },
  current: { next_actor: null, allowed_next: [], plan: { id: "plan-1", primary_target: "couch", scope: "Remove couch and debris", work_area: "parkway", required_equipment: ["truck"], quote_cents: 7200, policy_version: "v3", dispatch_location: null },
    job: { id: "job-1", vendor_id: "south_loop_services", vendor_label: "South Loop Services", status: "PAID", state_revision: 9, quote_cents: 7200, latest_submission_id: "sub-2", reservation_id: "res-1", payment_id: "pay-1", simulated: true },
    exception: null, payment: { id: "pay-1", job_id: "job-1", submission_id: "sub-2", verification_id: "ver-2", amount_cents: 7200, simulated: true } },
  sources: { items: [
    { id: "sig-1", source_role: "feed", provenance: "seeded", observed_at: "2026-09-12T13:50:00Z", received_at: "2026-09-12T13:55:00Z", reported_location: "1200 S Wabash", evidence_ids: ["ev-1"] },
    { id: "sig-2", source_role: "resident", provenance: "live", observed_at: "2026-09-13T09:00:00Z", received_at: "2026-09-13T09:05:00Z", reported_location: "1200 S Wabash", evidence_ids: [] } ] },
  service_records: { items: [{ id: "srv-1", signal_id: "sig-1", outcome: "MATCH", status: "COMPLETED", completed_at: "2026-09-11T10:00:00Z", looked_up_at: "2026-09-12T14:00:00Z", source_mode: "seeded", provenance: "seeded", error_code: null }] },
  facts: { classification: null, jurisdiction: null, geocode: null, official_conflict_record_id: "srv-1", official_record_status: "COMPLETED", official_conflict_state: "CONFIRMED", official_completed_at: "2026-09-11T10:00:00Z" },
  evidence: { original_before_evidence_id: "ev-b", current_after_evidence_id: "ev-a2", latest_submission_id: "sub-2", verification_id: "ver-2", inspection_id: null, accepted_submission_id: "sub-2", accepted_verification_id: "ver-2", resolved_at: "2026-09-13T12:00:00Z",
    history: { items: [
      { submission_id: "sub-1", job_id: "job-1", verification_id: "ver-1", before_evidence_id: "ev-b", after_evidence_id: "ev-a1", submitted_at: "2026-09-13T10:00:00Z", findings: null, components: { gps_within_30m: 30, after_later_than_before: 10, target_removed: 40, no_new_hazard: 10, area_clear: 0 }, total: 90, prerequisites: [], unmet: ["area_clear"], accepted: false },
      { submission_id: "sub-2", job_id: "job-1", verification_id: "ver-2", before_evidence_id: "ev-b", after_evidence_id: "ev-a2", submitted_at: "2026-09-13T11:00:00Z", findings: null, components: { gps_within_30m: 30, after_later_than_before: 10, target_removed: 40, no_new_hazard: 10, area_clear: 10 }, total: 100, prerequisites: [{ name: "same_scene", allowed: true, unmet: [] }], unmet: [], accepted: true } ] } },
  latest_decision: { id: "dec-9", decision_type: "RESOLVE", summary: "Accepted proof shows the parkway clear; closing the issue.", actor_label: "Steward", actor_type: "service", next_actor: null, next_event: null, created_at: "2026-09-13T12:00:00Z", evidence_ids: ["ev-a2"], event_id: 40 },
  timeline_url: "/api/issues/demo-couch/events",
};
const events = { issue_id: "demo-couch", events: [
  { id: 20, occurred_at: "2026-09-13T10:05:00Z", type: "SETTLEMENT_DENIED", actor_label: "Steward", actor_type: "service", outcome: "DENIED", reason_code: "SCORE_BELOW_THRESHOLD", summary: "90 of 95", entity_ids: { signal_id: null, job_id: "job-1", submission_id: "sub-1", exception_id: null, decision_id: null, payment_id: null }, evidence_ids: [], provenance: null, simulated: null, evidence_score: null, evidence_components: null },
  { id: 38, occurred_at: "2026-09-13T11:30:00Z", type: "PAYMENT_SETTLED", actor_label: "Steward", actor_type: "service", outcome: "OK", reason_code: null, summary: "Simulated $72 settlement", entity_ids: { signal_id: null, job_id: "job-1", submission_id: "sub-2", exception_id: null, decision_id: null, payment_id: "pay-1" }, evidence_ids: [], provenance: null, simulated: true, evidence_score: null, evidence_components: null } ] };
const envelope = (data: unknown) => new Response(JSON.stringify({ outcome: "OK", reason_code: null, data, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [] }), { status: 200, headers: { "content-type": "application/json" } });

// The RequirePersona wrapper reads global session state via useSession(); in the real app App.tsx
// loads it once on mount. This test renders IssueDetail standalone, so we drive the session store
// directly with loadSession() (same pattern as OperationsBoard.test.tsx and api/session.test.tsx).
beforeEach(async () => {
  resetSessionForTests();
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.includes("/events")) return Promise.resolve(envelope(events));
    if (url.startsWith("/api/issues/")) return Promise.resolve(envelope(detail));
    return Promise.resolve(envelope({ sandbox: true, notice: "", actor: { actor_id: "o", actor_type: "operator", label: "District operator (seeded)" }, personas: [] }));
  });
  await loadSession();
});
afterEach(() => vi.restoreAllMocks());

const mount = () => render(<MemoryRouter initialEntries={["/issues/demo-couch"]}><Routes><Route path="/issues/:issueId" element={<IssueDetail />} /></Routes></MemoryRouter>);

describe("IssueDetail", () => {
  it("leads with status, location, points against 70 and the last decision", async () => {
    mount();
    expect(await screen.findByRole("heading", { level: 1, name: "1200 S Wabash Ave" })).toBeInTheDocument();
    expect(screen.getAllByText("Resolved")[0]).toHaveClass("badge--resolved");
    expect(screen.getAllByText("100 points, 70 needed")[0]).toBeInTheDocument();
    expect(screen.getByText(/Accepted proof shows the parkway clear/)).toBeInTheDocument();
  });
  it("places the official completion beside newer observations and marks the accepted proof", async () => {
    mount();
    expect(await screen.findByText("Official 311 record")).toBeInTheDocument();
    expect(screen.getByText("Newer observations")).toBeInTheDocument();
    expect(screen.getByText(/Dispute confirmed/)).toBeInTheDocument();
    expect(screen.getByText("Accepted")).toHaveClass("badge--resolved");
    expect(screen.getByText("Superseded")).toBeInTheDocument();
    expect(screen.getAllByText("100 of 95 for payment")[0]).toBeInTheDocument();
  });
  it("keeps the denied settlement visible in the timeline and labels the payment simulated", async () => {
    mount();
    expect(await screen.findByText("Settlement denied")).toBeInTheDocument();
    expect(screen.getAllByText("Denied")[0]).toHaveClass("badge--denied");
    expect(screen.getByText("SETTLEMENT_DENIED")).toBeInTheDocument();
    expect(screen.getAllByText(/simulated/i).length).toBeGreaterThan(0);
  });
});
