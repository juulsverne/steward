import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetSessionForTests } from "../api/session";
import { CrewJob } from "./CrewJob";

const base = { id: "job-1", issue_id: "demo-couch", vendor_id: "south_loop_services", status: "ASSIGNED", state_revision: 2, location: "1200 S Wabash Ave", scope: "Remove couch and debris", work_area: "parkway", price_cents: 7200,
  proof_requirements: { check_in: true, before_image: true, fresh_after_image: true, same_scene: true, target_removed: true, no_new_hazard: true, area_clear: true },
  accepted_at: "2026-09-13T09:00:00Z", checkin_claimed_at: null, checked_in_at: null, submitted_at: null, latest_submission_id: null, rework_instructions: null, simulated: true, plan_id: "plan-1",
  primary_target: "couch", dispatch_location: { lat: 41.867, lon: -87.626, accuracy_m: 5, provenance: "seeded" }, required_equipment: ["truck"], crew_count: 2, reservation_id: "res-1", policy_version: "v3" };
let job: Record<string, unknown> = { ...base }; let posts: Array<{ url: string; init: RequestInit }> = []; let checkinFails = false; let proofReceiptFails = false;
const envelope = (data: unknown, status = 200) => new Response(JSON.stringify({ outcome: "OK", reason_code: null, data, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [] }), { status, headers: { "content-type": "application/json" } });

beforeEach(() => { resetSessionForTests(); job = { ...base }; posts = []; checkinFails = false; proofReceiptFails = false; vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
  const url = String(input);
  if (init?.method === "POST") { posts.push({ url, init: init! });
    if (url.endsWith("/check-in")) { if (checkinFails) { checkinFails = false; return Promise.reject(new Error("network down")); } job = { ...job, status: "CHECKED_IN", state_revision: 3, checked_in_at: "2026-09-13T09:30:00Z" }; return Promise.resolve(envelope({ record_id: "job-1", state_revision: 3 })); }
    if (url.endsWith("/proof")) { job = { ...job, status: "PROOF_SUBMITTED", state_revision: 4, latest_submission_id: "sub-1" }; return Promise.resolve(envelope({ record_id: "sub-1", state_revision: 4 }, 202)); }
  }
  if (url.includes("/receipt")) return proofReceiptFails ? Promise.reject(new Error("network down")) : Promise.resolve(envelope({ submission_id: "sub-1", job_id: "job-1", invocation_id: "inv-1", processing: "WAITING", updated_at: null, reason_code: null }));
  if (url.startsWith("/api/jobs/job-1")) return Promise.resolve(envelope(job));
  return Promise.resolve(envelope({ sandbox: true, notice: "", actor: { actor_id: "c", actor_type: "crew", label: "South Loop Services crew (seeded)", vendor_id: "south_loop_services" }, personas: [] }));
}); });
afterEach(() => vi.restoreAllMocks());

const mount = () => render(<MemoryRouter initialEntries={["/crew/jobs/job-1"]}><Routes><Route path="/crew/jobs/:jobId" element={<CrewJob />} /></Routes></MemoryRouter>);

describe("CrewJob", () => {
  it("shows the job, requirements and unlocks steps in order", async () => {
    mount();
    expect(await screen.findByRole("heading", { level: 1, name: "1200 S Wabash Ave" })).toBeInTheDocument();
    expect(screen.getByText(/\$72\.00/)).toHaveTextContent("simulated");
    expect(screen.getByText("Area clear")).toBeInTheDocument();
    expect(screen.getByText("Accepted")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check in" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Submit proof" })).toBeNull();
  });
  it("checks in with the demo coordinates and the expected revision", async () => {
    mount();
    await userEvent.click(await screen.findByRole("button", { name: /Use dispatch coordinates/ }));
    await userEvent.click(screen.getByRole("button", { name: "Check in" }));
    await waitFor(() => expect(screen.getAllByText("Checked in")[0]).toBeInTheDocument());
    const post = posts.find((p) => p.url.endsWith("/check-in"))!;
    expect(new Headers(post.init.headers).get("X-Steward-Expected-Revision")).toBe("2");
    expect(JSON.parse(post.init.body as string)).toMatchObject({ latitude: 41.867, longitude: -87.626 });
  });
  it("retries an ambiguous check-in with the same immutable request body and key", async () => {
    checkinFails = true; mount();
    await userEvent.click(await screen.findByRole("button", { name: /Use dispatch coordinates/ }));
    await userEvent.click(screen.getByRole("button", { name: "Check in" }));
    expect(await screen.findByText("Action not saved")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check in" }));
    await waitFor(() => expect(screen.getAllByText("Checked in")[0]).toBeInTheDocument());
    const attempts = posts.filter((p) => p.url.endsWith("/check-in"));
    expect(attempts).toHaveLength(2);
    expect(attempts[1].init.body).toBe(attempts[0].init.body);
    expect(new Headers(attempts[1].init.headers).get("Idempotency-Key")).toBe(new Headers(attempts[0].init.headers).get("Idempotency-Key"));
  });
  it("ignores a delayed location callback after a check-in attempt begins", async () => {
    const original = navigator.geolocation; let lateLocation: PositionCallback | null = null;
    Object.defineProperty(navigator, "geolocation", { configurable: true, value: { getCurrentPosition: (success: PositionCallback) => { lateLocation = success; } } });
    try {
      checkinFails = true; mount();
      await userEvent.click(await screen.findByRole("button", { name: "Use my location" }));
      await userEvent.click(screen.getByRole("button", { name: /Use dispatch coordinates/ }));
      await userEvent.click(screen.getByRole("button", { name: "Check in" }));
      expect(await screen.findByText("Action not saved")).toBeInTheDocument();
      lateLocation!({ coords: { latitude: 1, longitude: 2, accuracy: 3 } } as GeolocationPosition);
      await userEvent.click(screen.getByRole("button", { name: "Check in" }));
      await waitFor(() => expect(screen.getAllByText("Checked in")[0]).toBeInTheDocument());
      const attempts = posts.filter((p) => p.url.endsWith("/check-in"));
      expect(attempts).toHaveLength(2);
      expect(attempts[1].init.body).toBe(attempts[0].init.body);
    } finally { Object.defineProperty(navigator, "geolocation", { configurable: true, value: original }); }
  });
  it("starts a fresh check-in attempt when location corrects a failed payload", async () => {
    const original = navigator.geolocation;
    Object.defineProperty(navigator, "geolocation", { configurable: true, value: { getCurrentPosition: (success: PositionCallback) => success({ coords: { latitude: 1, longitude: 2, accuracy: 3 } } as GeolocationPosition) } });
    try {
      checkinFails = true; mount();
      await userEvent.click(await screen.findByRole("button", { name: /Use dispatch coordinates/ }));
      await userEvent.click(screen.getByRole("button", { name: "Check in" }));
      expect(await screen.findByText("Action not saved")).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Use my location" }));
      await userEvent.click(screen.getByRole("button", { name: "Check in" }));
      await waitFor(() => expect(screen.getAllByText("Checked in")[0]).toBeInTheDocument());
      const attempts = posts.filter((p) => p.url.endsWith("/check-in"));
      expect(attempts).toHaveLength(2);
      expect(new Headers(attempts[1].init.headers).get("Idempotency-Key")).not.toBe(new Headers(attempts[0].init.headers).get("Idempotency-Key"));
      expect(JSON.parse(attempts[1].init.body as string)).toMatchObject({ latitude: 1, longitude: 2, accuracy_m: 3 });
    } finally { Object.defineProperty(navigator, "geolocation", { configurable: true, value: original }); }
  });
  it("submits proof as multipart, then shows received and the verbatim receipt status", async () => {
    job = { ...base, status: "CHECKED_IN", state_revision: 3, checked_in_at: "2026-09-13T09:30:00Z" };
    mount();
    const file = new File(["x"], "after.jpg", { type: "image/jpeg" });
    await userEvent.upload(await screen.findByLabelText("Before photo"), file);
    await userEvent.upload(screen.getByLabelText("After photo"), file);
    await userEvent.click(screen.getByRole("button", { name: "Submit proof" }));
    expect(await screen.findByText(/Received, submission sub-1/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("WAITING")).toBeInTheDocument());
    const post = posts.find((p) => p.url.endsWith("/proof"))!;
    expect(post.init.body).toBeInstanceOf(FormData);
    expect((post.init.body as FormData).get("metadata")).toBe("{}");
  });
  it("keeps a received proof saved when its receipt status fails, then retries that receipt", async () => {
    proofReceiptFails = true; job = { ...base, status: "CHECKED_IN", state_revision: 3, checked_in_at: "2026-09-13T09:30:00Z" };
    mount(); const file = new File(["x"], "after.jpg", { type: "image/jpeg" });
    await userEvent.upload(await screen.findByLabelText("Before photo"), file);
    await userEvent.upload(screen.getByLabelText("After photo"), file);
    await userEvent.click(screen.getByRole("button", { name: "Submit proof" }));
    expect(await screen.findByText(/Received, submission sub-1/)).toBeInTheDocument();
    expect(screen.getByText("Proof saved; status unavailable")).toBeInTheDocument();
    proofReceiptFails = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("WAITING")).toBeInTheDocument());
    expect(posts.filter((p) => p.url.endsWith("/proof"))).toHaveLength(1);
  });
  it("shows rework instructions and only the after input on rework", async () => {
    job = { ...base, status: "REWORK_REQUIRED", state_revision: 6, checked_in_at: "2026-09-13T09:30:00Z", latest_submission_id: "sub-1", rework_instructions: "Debris remains at the curb; clear the full area." };
    mount();
    expect(await screen.findByText(/Debris remains at the curb/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Before photo")).toBeNull();
    expect(screen.getByLabelText("After photo")).toBeInTheDocument();
  });
});
