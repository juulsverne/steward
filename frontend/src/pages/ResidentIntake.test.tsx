import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetSessionForTests } from "../api/session";
import { ResidentIntake } from "./ResidentIntake";

const envelope = (data: unknown, status = 200) => new Response(JSON.stringify({ outcome: "OK", reason_code: null, data, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [] }), { status, headers: { "content-type": "application/json" } });
let posts: FormData[] = []; let fail = false;
beforeEach(() => { resetSessionForTests(); posts = []; fail = false; vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
  const url = String(input);
  if (init?.method === "POST") { posts.push(init.body as FormData); if (fail) return Promise.resolve(new Response(JSON.stringify({ outcome: "ERROR", reason_code: "VALIDATION_ERROR", data: null, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [] }), { status: 422, headers: { "content-type": "application/json" } }));
    return Promise.resolve(envelope({ receipt_id: "rcpt-1", signal_id: "sig-9", received_at: "2026-09-14T15:00:00Z", accepted: true, processing: "PENDING" }, 202)); }
  if (url.includes("/receipt")) return Promise.resolve(envelope({ processing: "COMPLETED", invocation_id: "inv-2", updated_at: "2026-09-14T15:01:00Z", reason_code: null }));
  return Promise.resolve(envelope({ sandbox: true, notice: "Sandbox", actor: { actor_id: "r", actor_type: "resident", label: "Resident 2 (seeded)" }, personas: [] }));
}); });
afterEach(() => vi.restoreAllMocks());
const mount = () => render(<MemoryRouter><ResidentIntake /></MemoryRouter>);

describe("ResidentIntake", () => {
  it("asks only for description, location, optional time and photo", async () => {
    mount();
    expect(await screen.findByLabelText("What did you see?")).toBeInTheDocument();
    expect(screen.getByLabelText("Where?")).toBeInTheDocument();
    expect(screen.getByLabelText("When did you see it? (optional)")).toBeInTheDocument();
    expect(screen.getByLabelText("Photo (optional)")).toBeInTheDocument();
    expect(screen.queryByText(/urgency|vendor|price|jurisdiction|service code/i)).toBeNull();
  });
  it("submits multipart without observed_at when unknown, then shows the receipt only after 202", async () => {
    mount();
    await userEvent.type(await screen.findByLabelText("What did you see?"), "Couch still on the parkway");
    await userEvent.type(screen.getByLabelText("Where?"), "1200 S Wabash Ave");
    await userEvent.click(screen.getByLabelText("I don't know"));
    await userEvent.click(screen.getByRole("button", { name: "Send report" }));
    expect(await screen.findByText("Report saved")).toBeInTheDocument();
    expect(screen.getByText("rcpt-1")).toBeInTheDocument();
    expect(posts[0].get("description")).toBe("Couch still on the parkway");
    expect(posts[0].has("observed_at")).toBe(false);
    expect(posts[0].has("image")).toBe(false);
    await waitFor(() => expect(screen.getByText("COMPLETED")).toBeInTheDocument());
  });
  it("keeps the form on failure", async () => {
    fail = true; mount();
    await userEvent.type(await screen.findByLabelText("What did you see?"), "Couch");
    await userEvent.type(screen.getByLabelText("Where?"), "Nowhere St");
    await userEvent.click(screen.getByRole("button", { name: "Send report" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Validation error");
    expect(screen.getByLabelText("What did you see?")).toHaveValue("Couch");
  });
});
