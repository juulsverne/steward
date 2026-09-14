import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, mutate, newIdempotencyKey, pollUntil, read, reasonText, upload } from "./client";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
const ok = (data: unknown) => ({ outcome: "OK", reason_code: null, data, unmet: [], allowed_next: [], evidence_ids: [], event_ids: [] });

afterEach(() => vi.restoreAllMocks());

describe("read", () => {
  it("unwraps data from an OK envelope", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(ok({ ok: true })));
    await expect(read<{ ok: boolean }>("/api/x")).resolves.toEqual({ ok: true });
    const init = vi.mocked(fetch).mock.calls[0][1]!;
    expect(init.credentials).toBe("same-origin");
    expect(new Headers(init.headers).get("X-Steward-Request")).toBeNull();
  });
  it("throws ApiError with reason code on DENIED", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ ...ok(null), outcome: "DENIED", reason_code: "ROLE_FORBIDDEN" }, 403));
    const error = await read("/api/x").catch((e) => e as unknown);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(403); expect((error as ApiError).reasonCode).toBe("ROLE_FORBIDDEN"); expect((error as ApiError).outcome).toBe("DENIED");
  });
  it("throws ApiError on a network failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
    const error = await read("/api/x").catch((e) => e as unknown);
    expect(error).toBeInstanceOf(ApiError); expect((error as ApiError).status).toBe(0); expect((error as ApiError).reasonCode).toBe("NETWORK");
  });
});

describe("mutate", () => {
  it("sends intent headers, idempotency key and expected revision as JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(ok({ record_id: "j1", state_revision: 2 }), 202));
    const result = await mutate("/api/jobs/j1/accept", { a: 1 }, { idempotencyKey: "k-1", expectedRevision: 1 });
    expect(result.status).toBe(202); expect(result.data).toEqual({ record_id: "j1", state_revision: 2 });
    const init = vi.mocked(fetch).mock.calls[0][1]!; const headers = new Headers(init.headers);
    expect(init.method).toBe("POST"); expect(headers.get("X-Steward-Request")).toBe("1");
    expect(headers.get("Idempotency-Key")).toBe("k-1"); expect(headers.get("X-Steward-Expected-Revision")).toBe("1");
    expect(headers.get("Content-Type")).toBe("application/json"); expect(init.body).toBe(JSON.stringify({ a: 1 }));
  });
  it("sends no body and no content type when body is undefined", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(ok({ record_id: "j1" })));
    await mutate("/api/jobs/j1/accept", undefined, { idempotencyKey: "k-2" });
    const init = vi.mocked(fetch).mock.calls[0][1]!;
    expect(init.body).toBeUndefined(); expect(new Headers(init.headers).get("Content-Type")).toBeNull();
  });
  it("throws ApiError carrying unmet and allowed_next on DENIED", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ ...ok(null), outcome: "DENIED", reason_code: "REVISION_CONFLICT", unmet: ["x"], allowed_next: ["refresh"] }, 409));
    const error = await mutate("/api/x", {}, { idempotencyKey: "k" }).catch((e) => e as unknown);
    expect((error as ApiError).status).toBe(409); expect((error as ApiError).unmet).toEqual(["x"]); expect((error as ApiError).allowedNext).toEqual(["refresh"]);
  });
});

describe("upload", () => {
  it("sends FormData without a content type header", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(ok({ record_id: "s1" }), 202));
    const form = new FormData(); form.set("description", "couch");
    await upload("/api/signals", form, { idempotencyKey: "k-3" });
    const init = vi.mocked(fetch).mock.calls[0][1]!;
    expect(init.body).toBe(form); expect(new Headers(init.headers).get("Content-Type")).toBeNull();
    expect(new Headers(init.headers).get("Idempotency-Key")).toBe("k-3");
  });
});

describe("newIdempotencyKey", () => {
  it("matches the server pattern", () => {
    expect(newIdempotencyKey("ui.accept")).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/);
  });
});

describe("pollUntil", () => {
  it("returns when terminal and reports exhaustion otherwise", async () => {
    let n = 0;
    const r = await pollUntil(async () => ++n, (v) => v >= 3, { intervalMs: 1, maxMs: 1000 });
    expect(r).toEqual({ value: 3, exhausted: false });
    const e = await pollUntil(async () => "PENDING", () => false, { intervalMs: 1, maxMs: 10 });
    expect(e.value).toBe("PENDING"); expect(e.exhausted).toBe(true);
  });
});

describe("reasonText", () => {
  it("humanizes a code", () => { expect(reasonText("REVISION_CONFLICT")).toBe("Revision conflict"); expect(reasonText(null)).toBe("Unknown reason"); });
});
