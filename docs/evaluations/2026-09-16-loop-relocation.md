# Loop demo relocation — September 16, 2026

The public demo anchor is now **State St & Madison St (demo)**, with approximate seeded coordinates **41.88206, -87.62780**. It identifies a fictional case near the [State/Madison intersection](https://chicagostudies.uchicago.edu/grid), not a real incident or surveyed address. The previous primary location was removed from the current source and public presentation for privacy.

## What changed

- Primary fixture address, geocode, service-record matching, seed and offline harness; the fictional policy boundary includes the new pin.
- Public district display and initial map center. Internal district, provider, and policy IDs remain stable.
- Documentation and historical export location fields, with redaction notes rather than claims of new evaluation results.
- UI screenshots, regenerated from an isolated relocated copy of a completed local demo database, with agent execution disabled. Original test receipts still describe their dated runs.

The existing synthetic images are unchanged. They do not depict the actual Loop intersection; their original generation prompts remain in [image provenance](../../data/images/PROVENANCE.md).

## State preservation and validation

The [copy-only migration utility](../../scripts/relocate_demo_sqlite.py) derives the source demo anchor, replaces its text variants and nearby coordinate pairs, and preserves the original database. Run it only with the source service stopped; pending/running invocations are refused. Use a new destination and do not install an output from a failed run. It checks SQLite integrity, foreign keys, and protected financial, job, issue, and invocation records.

The local replay retains one resolved issue at 100 evidence points, one paid simulated job, one $72 simulated payment, two ledger entries, and five invocations. Available budget remains $428. Both stored check-in distances remain unchanged. No fresh Bedrock inference, dispatch, or settlement was requested.

- Independent targeted backend review: **91 tests passed** across relocation, context, intake, scoring, and policy.
- After the alias/cleanup review fixes: **4 migration tests passed** independently, with Ruff clean and review approved.
- Frontend: **68 tests passed**; TypeScript/Vite production build passed.
- Screenshot inspection covers Board, Issue Detail, handled exception, Crew, and Resident intake in desktop/mobile and light/dark presentations.

## Hosted rollout

Pending AWS sign-in at the time this note was prepared. Local screenshots and migration validation do not establish that the hosted database has changed. The hosted rollout requires a fresh backup, stopped-service migration to a separate database, checked source/frontend installation, restart, and public API/browser verification before recording completion here.

## Historical scope

This change updates the current repository contents. It does not rewrite earlier Git commits or erase independently cached copies of the former screenshots. Private original databases remain available for rollback and historical verification. The relocation is a presentation/data-privacy change, not a new live acceptance or model-qualification result.
