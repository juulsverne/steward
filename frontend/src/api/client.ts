import type { Outcome, ToolResult } from "../types";

export class ApiError extends Error {
  status: number; outcome: Outcome; reasonCode: string | null; unmet: string[]; allowedNext: string[]; data: unknown;
  constructor(status: number, envelope: Partial<ToolResult<unknown>>, message?: string) {
    super(message ?? `${envelope.outcome ?? "ERROR"} ${envelope.reason_code ?? status}`);
    this.name = "ApiError"; this.status = status; this.outcome = envelope.outcome ?? "ERROR";
    this.reasonCode = envelope.reason_code ?? null; this.unmet = envelope.unmet ?? [];
    this.allowedNext = envelope.allowed_next ?? []; this.data = envelope.data ?? null;
  }
}

export interface Envelope<T> extends ToolResult<T> { status: number }
export interface MutateOptions { idempotencyKey: string; expectedRevision?: number | null }
export interface PollOptions { intervalMs?: number; maxMs?: number; backoff?: number; signal?: AbortSignal }

export function newIdempotencyKey(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}-${Math.random().toString(36).slice(2, 10)}`;
  const raw = `${prefix}-${uuid}`.replace(/[^A-Za-z0-9._:-]/g, "-");
  return (/^[A-Za-z0-9]/.test(raw) ? raw : `k${raw}`).slice(0, 128);
}

export function reasonText(code: string | null | undefined): string {
  if (!code) return "Unknown reason";
  const words = code.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

async function send<T>(path: string, init: RequestInit): Promise<Envelope<T>> {
  let response: Response;
  try { response = await fetch(path, { credentials: "same-origin", ...init }); }
  catch (error) { throw new ApiError(0, { outcome: "ERROR", reason_code: "NETWORK" }, (error as Error).message); }
  let envelope: ToolResult<T>;
  try { envelope = (await response.json()) as ToolResult<T>; }
  catch { throw new ApiError(response.status, { outcome: "ERROR", reason_code: "INVALID_RESPONSE" }); }
  if (!response.ok || envelope.outcome === "DENIED" || envelope.outcome === "NOT_FOUND" || envelope.outcome === "ERROR") {
    throw new ApiError(response.status, envelope);
  }
  return { ...envelope, status: response.status };
}

export async function readEnvelope<T>(path: string): Promise<Envelope<T>> {
  return send<T>(path, { method: "GET", headers: { Accept: "application/json" } });
}

export async function read<T>(path: string): Promise<T> {
  const envelope = await readEnvelope<T>(path);
  if (envelope.data === null || envelope.data === undefined) throw new ApiError(envelope.status, { ...envelope, outcome: "ERROR", reason_code: "EMPTY_DATA" });
  return envelope.data;
}

function intentHeaders(opts: MutateOptions): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json", "X-Steward-Request": "1", "Idempotency-Key": opts.idempotencyKey };
  if (opts.expectedRevision !== undefined && opts.expectedRevision !== null) headers["X-Steward-Expected-Revision"] = String(opts.expectedRevision);
  return headers;
}

export async function mutate<T>(path: string, body: unknown | undefined, opts: MutateOptions): Promise<Envelope<T>> {
  const headers = intentHeaders(opts);
  const init: RequestInit = { method: "POST", headers };
  if (body !== undefined) { headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
  return send<T>(path, init);
}

export async function upload<T>(path: string, form: FormData, opts: MutateOptions): Promise<Envelope<T>> {
  return send<T>(path, { method: "POST", headers: intentHeaders(opts), body: form });
}

const sleep = (ms: number, signal?: AbortSignal) => new Promise<void>((resolve) => {
  const id = setTimeout(resolve, ms); signal?.addEventListener("abort", () => { clearTimeout(id); resolve(); }, { once: true });
});

export async function pollUntil<T>(fetchValue: () => Promise<T>, isTerminal: (value: T) => boolean, opts: PollOptions = {}): Promise<{ value: T; exhausted: boolean }> {
  const { intervalMs = 1500, maxMs = 60000, backoff = 1.5, signal } = opts;
  const started = Date.now(); let wait = intervalMs; let value = await fetchValue();
  while (!isTerminal(value)) {
    if (signal?.aborted || Date.now() - started >= maxMs) return { value, exhausted: true };
    await sleep(Math.min(wait, Math.max(0, maxMs - (Date.now() - started))), signal);
    if (signal?.aborted) return { value, exhausted: true };
    wait = Math.min(wait * backoff, 8000); value = await fetchValue();
  }
  return { value, exhausted: false };
}
