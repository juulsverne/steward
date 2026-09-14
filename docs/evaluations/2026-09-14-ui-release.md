# Public UI release — September 14, 2026

The owner authorized updating the existing CloudFront site before submission. The reviewed frontend from `2f31548a3823db57621ad3bc406d93908f58dcdd` is deployed at https://d1uke66gfefpu4.cloudfront.net.

Backend source, `pyproject.toml` and `uv.lock` have no differences between the deployed backend `57e7e27` and this reviewed source. Only frontend assets were updated; the API was not restarted and the database was not reset. The historical live acceptance results remain attached to [the original hosted run](2026-09-14-hosted-acceptance.md), not relabeled as a new live run.

## Release evidence

- Built from an isolated archive of the full reviewed commit using locked npm dependencies; TypeScript and Vite build passed.
- Frontend regression suite rerun: 13 files, **68 tests passed**.
- Private frontend tar SHA-256: `b39c0edb106cc8beabcfdcc50c31723a706d37b9da3009430ca3bf1965823c7e`; verified on the instance before extraction.
- Fresh backup service completed before installation. Old dist retained at `/opt/steward/ui-releases/2f31548a3823db57621ad3bc406d93908f58dcdd/previous-dist`.
- New hashed assets copied first, then index.html replaced atomically. Existing hashed assets remain available for already-open browser pages.
- CloudFront returned HTTP 200 and references `index-DXzffniY.js` and `index-CRLJ6_ra.css`. No cache invalidation needed: distribution caching is disabled.
- Before and after: service active, payments **1**, jobs **1**, events **37**. No new model invocation or settlement was requested.
- Live browser Board and Issue Detail rendered the restored civic frame, paired evidence, accepted 100-point proof, earlier failed 90-point proof, official-record conflict, and the saved $72 simulated settlement.

Instance UI revision is recorded in `/opt/steward/app/frontend/DEPLOYED_UI_COMMIT`. To roll back this UI, restore the retained previous index.html; its hashed assets remain in place. Backend, database and secrets do not need changing.

This is a UI release and smoke check. Full browser-driven acceptance repeat, broader evaluation and unproven disaster-recovery scenarios remain open. Keep the submitted repository and materials frozen after the deadline according to the organizer's final reminder.
