# Steward documentation

For a project overview, start with the [README](../README.md). To try the prototype, use [RUNNING.md](RUNNING.md). Before changing the implementation, read the PRD, architecture, and build guide. Hackathon deadlines and submission checklists below are historical: the project was not submitted.

The public demo was relocated to the seeded Loop anchor after the dated evidence below was captured. Historical records redact the prior location and do not claim a later rerun or new coordinates.

| Document | What it is | Read it when |
|---|---|---|
| [PRD.md](PRD.md) | Product requirements v3.2: scope authority, actors, journey, agent behavior, requirements | Before any product or scope decision |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Code and deployment contract: boundaries, tools, data, policy, verification | Before changing code |
| [BUILD_PLAN.md](BUILD_PLAN.md) | Complete build guide: tiers, task cards, coding-agent assignments, review gates | When picking up or delegating a task |
| [DEMO.md](DEMO.md) | Sixteen acceptance criteria and the demo runbook | Before claiming a criterion passes |
| [EVALUATION.md](EVALUATION.md) | Twenty-two-scenario internal evaluation protocol | Before running or reporting an evaluation |
| [MODEL_SELECTION.md](MODEL_SELECTION.md) | Which Bedrock model does each job, costs, screen results, qualification gates | Before changing a model or prompt |
| [SUBMISSION.md](SUBMISSION.md) | Original hackathon submission checklist and deadline (not submitted) | When reviewing project history |
| [VISION.md](VISION.md) | Post-competition company direction | Only after the couch works |

## Dated evidence

- [evaluations/2026-09-13-vision-spike.md](evaluations/2026-09-13-vision-spike.md): the passed Tier 1A vision gate, 12/12 expected outcomes on Sonnet.
- [evaluations/2026-09-13-model-screen.json](evaluations/2026-09-13-model-screen.json): the exported eight-model component screen, produced by `scripts/export_model_screen.py` from local run artifacts.
- [reviews/2026-09-13-document-review.md](reviews/2026-09-13-document-review.md): reconciliation of the handoff with the checkout.

Local-only notes live in `docs/local/` and historical plans in `docs/plans/`. Both are gitignored, and neither overrides the documents above. After editing any document, run `uv run --no-sync python scripts/check_docs.py` to confirm every relative link and anchor still resolves.
