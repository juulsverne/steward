# Steward frontend frame (P1) — design

Status: proposed, 2026-09-14. Written after the B13 API gate work; nothing under `frontend/` exists yet. This document settles the shared choices that P2–P6 page work depends on. Product behavior, actors, authority and the sixteen acceptance criteria come from [PRD](../../PRD.md) §5–§7 and [DEMO](../../DEMO.md); the visual direction comes from `.impeccable.md` (credible, clear, contemporary; light default with a dark theme). Where those documents leave latitude, this spec records the choice and marks it **[choice]** so it can be overridden before implementation.

## 1. Scope

In scope for P1 (from [BUILD_PLAN](../../BUILD_PLAN.md) §8):

- `frontend/` Vite + React + TypeScript project with `npm run build` and `npm run typecheck`.
- Typed API client over the shipped B10 contract: session and persona, reads for board, issue detail, timeline, crew jobs, exceptions, evidence; browser mutations with the required headers; `ToolResult` envelope and error mapping.
- Application frame: district/demo header with sandbox notice, persona switcher (Operator, Crew per vendor, Resident), navigation, route skeleton for the five surfaces, pending/error/empty primitives, theme tokens and toggle.
- FastAPI serving of the built files with a client-route fallback that never shadows `/api`.

Out of scope: page content for Issue Detail, Board, Inbox, Crew Form, Resident intake (P2–P6); hosting (H4); any new API authority.

## 2. Constraints taken from the existing system

- Every browser mutation must send an allowed `Origin`, `X-Steward-Request: 1` and an `Idempotency-Key` (`[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`); investigation-style writes need `X-Steward-Expected-Revision`. Missing headers fail with 403/400, and there is no CORS: the app is same-origin in production and uses a Vite `/api` proxy in development with the dev origin listed in `STEWARD_DEVELOPMENT_ORIGINS` (local HTTP mode only).
- The persona is an HttpOnly, SameSite=Strict cookie set by `POST /api/demo/persona`. The browser never sees or stores actor identity; the client re-reads `GET /api/demo/session` after switching. Service tokens never reach the browser.
- Every response is `ToolResult{outcome, reason_code, data, unmet, allowed_next, evidence_ids, event_ids}`. Status comes only from saved data; model prose never sets Paid, Verified or Resolved (PRD §7).
- Processing is asynchronous: intake returns 202 with `processing: "PENDING"`, and `GET /api/signals/{id}/receipt` plus `GET /api/invocations/{id}` expose saved status. The plan says start with polling.
- NFR-08: complete the flow by keyboard, labeled controls, visible focus, colors paired with text, narrow mobile layout for crew and intake, navigation survives map tile failure.

## 3. Architecture

```
browser ── same origin ──> FastAPI (api.py)
   │  /api/*  (JSON, cookie session)          existing routes, unchanged
   │  /assets/*, /index.html                   StaticFiles from frontend/dist
   └  any other GET path -> index.html         client-route fallback (SPA)

frontend/src
  main.tsx            React root, router, theme bootstrap
  App.tsx             frame: header, persona switcher, nav, <Outlet/>
  api/schema.d.ts     generated from /openapi.json (openapi-typescript)   [choice]
  api/client.ts       fetch wrapper: envelope, headers, errors, polling helper
  api/session.ts      session store: personas, actor, switch(), refresh()
  types.ts            hand-written aliases over schema.d.ts for page code
  theme.css           tokens (light default, dark override), reset, typography
  components/         StatusBadge, PendingState, ErrorNotice, EmptyState,
                      Money, Timestamp, EvidenceImage, PageHeader
  pages/              Board, IssueDetail, OperatorInbox, CrewForm, ResidentIntake
                      (P1 ships route shells with loading/error states only)
```

**Static serving [choice].** `api.py` mounts `frontend/dist/assets` at `/assets` and returns `index.html` for GET requests whose path does not start with `/api`, `/internal`, `/health`, `/openapi.json` or `/assets`. The fallback is registered after every API route so a typo in an API path still returns the API's JSON 404, not HTML. When `frontend/dist` is absent (tests, API-only hosts) the fallback is not registered and `/` returns the existing JSON 404, so no backend test changes behavior. Built files are served with `Cache-Control: no-store` for `index.html` and long-lived caching for hashed `/assets`.

**Typed client [choice].** Types are generated from the running API's OpenAPI document (`npm run types`, which runs `openapi-typescript` against `http://127.0.0.1:8000/openapi.json`) and the generated file is committed, so a contract change shows up as a typed diff instead of a runtime surprise. `client.ts` exposes one `call<T>(path, init)` that unwraps `ToolResult`, throws a typed `ApiError{status, outcome, reason_code, unmet, allowed_next}` for non-`OK` outcomes, and helpers `read()`, `mutate()` (adds intent headers, generates and reuses one idempotency key per logical submission until it succeeds or is abandoned) and `pollUntil()` (bounded polling with backoff for receipt and invocation status; the page decides what "terminal" means).

**Session.** On load the frame calls `GET /api/demo/session`; the response's `actor` (or `null`) drives which navigation entries and pages are available. Switching persona posts the choice, then re-reads the session; on 403/400 the switcher shows the reason and keeps the previous selection. Nothing about the actor is written to browser storage. Theme preference is the only stored value (`localStorage` key `steward-theme`), read before first paint to avoid a flash.

**Routing [choice].** React Router with `/` (Board), `/issues/:issueId` (Issue Detail), `/inbox` (Operator Inbox), `/crew` and `/crew/jobs/:jobId` (Crew Form), `/report` (Resident intake). Deep links work through the server fallback. Pages a persona cannot use render an explanation with the persona switcher, never a blank screen.

## 4. Visual system

- Tokens in `theme.css`: surfaces (warm neutral), ink (deep navy), action (restrained teal), status pairs (watching, active, attention, resolved, denied) each with a text label, rules and spacing scale, radii, focus ring. Dark theme redefines the same tokens under `[data-theme="dark"]` and under `prefers-color-scheme: dark` when no explicit choice exists. Light is the default.
- Typography [choice]: Public Sans for interface text and Newsreader for page-level headings, self-hosted through `@fontsource` packages so builds do not depend on a font CDN; system fallbacks declared. Whether headings stay serif is a design review item; the token indirection makes the swap one line.
- No component library [choice]. The five surfaces need a small set of primitives, and restraint is a stated principle; hand-written components keep bundle size and accessibility under direct control. Leaflet is added in P3 only.
- Status colors are never the only signal: `StatusBadge` always renders the label. Scores read as "85 points, 70 needed", never as percentages.

## 5. Error and pending behavior

| Situation | Frame behavior |
|---|---|
| Read fails (network, 5xx, `STORAGE_UNAVAILABLE`) | `ErrorNotice` with the reason code text and a retry action; stale data stays visible and is labeled as of its fetch time |
| 403 `ORIGIN_FORBIDDEN` / `REQUEST_INTENT_REQUIRED` | Developer-facing notice naming the missing header or origin (only happens in misconfigured dev) |
| 409 `REVISION_CONFLICT` / `STATE_CONFLICT` | Refresh the record and tell the user the item changed; the form keeps its input |
| 409 `IDEMPOTENCY_CONFLICT` | Treat as "already submitted with different content"; new key on the next deliberate submission |
| 422 `VALIDATION_ERROR` | Map `unmet`/details to field messages; keep form state |
| Mutation accepted (202) | Show "received" with the receipt id; start bounded polling; display saved processing status verbatim (`PENDING`, `RUNNING`, `WAITING`, `COMPLETED`, `ERROR`) |
| Polling exhausted | Say processing is still saved and offer manual refresh; never invent completion |

Presentation-only feedback (button pressed, spinner) is immediate; anything that reads as a saved fact waits for the server response.

## 6. Testing

- `npm run typecheck` (`tsc --noEmit` over all sources) and `npm run build` are required before page work starts (BUILD_PLAN P1).
- Vitest + Testing Library [choice]: client envelope/error mapping with mocked `fetch`; idempotency key reuse across a retried submission; persona switcher re-reads session and preserves selection on failure; theme toggle persists only the theme; route shells render pending, error and empty states with accessible names.
- Python (`tests/test_static_frontend.py`): with a temporary `dist`, `/` and `/issues/x` return `index.html`, `/api/unknown` still returns the API JSON error, `/assets/...` serves files with immutable caching, and without `dist` behavior is unchanged.
- Manual check before P2: refresh a deep issue URL, switch persona, confirm permissions and data come from the API; verify contrast in both themes, keyboard focus order, reduced motion and a 360 px layout.

## 7. Open choices for the owner

1. Build the frontend in this session, or hand this spec to the person who planned to build it. (Another session recorded that the user intended to build the frontend themselves.)
2. Generated OpenAPI types versus hand-written `types.ts` only.
3. Serif headings (Newsreader) versus all-sans.
4. React Router versus a smaller hand-rolled router (five routes).

Defaults if no answer: generated types, React Router, serif headings behind a token, and P1 only after an explicit go-ahead.
