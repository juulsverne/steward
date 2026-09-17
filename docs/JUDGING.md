# Testing and submission audit — September 14, 2026

> September 16 update: the repository uses the Loop demo anchor; the previously hosted case has not yet been migrated. The instructions below describe the updated local case and apply to hosting only after that rollout. See the [relocation notes](evaluations/2026-09-16-loop-relocation.md).

Checked beginning around 5:30 PM Chicago time. **Submission is not complete.** This is an evidence checklist, not a legal eligibility certification.

## URLs and current versions

- Public judging URL: https://d1uke66gfefpu4.cloudfront.net — health returned OK during this audit. No custom domain is necessary for this route; use this HTTPS address in the submission.
- Public source: https://github.com/juulsverne/steward — GitHub API confirmed public visibility and detected MIT license. The initial 5:30 PM audit found main at `57e7e27`; final reviewed source publication follows the UI release.
- Local reviewed UI: `2f31548` on `codex/finish-review`. Its frontend is now deployed; backend source is identical to the existing hosted version. The browser preview at http://127.0.0.1:8099/issues/demo-couch uses copied completed-case data and has model execution disabled. It is only reachable on the builder's computer.
- `architecture.png` and `docs/architecture.svg` are included in the final reviewed source; the PNG is also attached to the Devpost draft.

## Try the saved case now

1. Open the public URL, or the local preview for the restored design.
2. Select **District operator (seeded)**. These are demo personas, not real accounts.
3. On Board, open **State St & Madison St (demo)**. Inspect official completion versus newer observations, original photo, failed middle proof, accepted after proof, policy points, and the simulated settlement. Expand **Open audit history and event references** for the full timeline.
4. Open Inbox, expand **Decided and handled**, and open the completion exception. The completed case has no pending completion action.
5. Select **South Loop Services crew (seeded)**, open Crew and its job. Inspect acceptance, check-in, proof and simulated payment. Switching to another vendor should not expose this crew's job.

The saved couch is already resolved. Sending another observation is not a reliable way to replay that same scenario. There is no browser reset/replay control or separate per-judge database. The public sandbox is shared; persona selection isolates access, not case state.

## Full manual run on a fresh local store

Use the README setup and authenticated Bedrock profile. Start a separate named test store with runtime enabled; do not reset the public judging store. Run only one live model workload at a time. The existing API driver has passed; this exact browser sequence still needs a recorded complete run and repeat.

1. Seed the fresh store and start its API. Wait for the initial investigation to finish. Operator Board should show one watching case, 65 evidence points and no dispatch.
2. Select **Resident 2 (seeded)**. In Report, enter `A sofa and dumped bags still obstruct the walkway at State St & Madison St (demo).` Location: `State St & Madison St (demo)`. Observation time: September 12, 2026 at **9:18 AM Chicago time** (`2026-09-12T14:18:00Z`). This is explicitly a supplied demo timestamp, not a new real observation. No extra resident photo is needed for this fixture. Submit and wait for the receipt's processing result.
3. Select Operator. Wait for the agent's investigation and dispatch. Inspect the dispute and the $72 simulated work order. Use the vendor actually assigned by the agent.
4. Select that vendor's crew. Open the job, accept it, select **Use dispatch coordinates, demo**, then check in. Do not use your actual location for the seeded Chicago scenario.
5. Submit the first proof: `data/images/before.jpg` as Before and `data/images/middle.jpg` as After. Fixture times are September 12 at **8:55 AM** and **7:00 PM Chicago time**, respectively (`13:55Z` and next-day `00:00Z`). These are supplied synthetic-fixture times. Wait for processing; inspect the failed area-clear requirement and blocked payment. The recorded API run scored this 90 against a 95 payment threshold; a differing live model result must be investigated, not edited to match.
6. Select Operator, open the pending Inbox exception and choose **Request completion** if the server allows it. Wait for the saved decision and rework instruction.
7. Return to the same crew/job. Submit `data/images/after.jpg` as the new After proof, timestamp September 12 at **8:00 PM Chicago time** (`2026-09-13T01:00:00Z`). Keep the original before proof. Wait for processing.
8. Confirm accepted verification, exactly one $72 simulated settlement, resolved issue, and Board budget $428 available / $0 reserved / $72 spent. Check the rejected proof and operator decision remain in history.
9. Repeat from another fresh local store and compare outcomes. Do not claim a full browser repeat from automated driver evidence.

For the automated developer check, see [README](RUNNING.md#4-run-the-couch-journey) and [DEMO](DEMO.md). A clone running live inference needs the tester's AWS credentials and incurs their costs, so it is a developer fallback, not the primary free judging route. Judges should use the owner-funded hosted app without receiving AWS keys or service tokens.

## Official submission cross-check

Sources reviewed: [overview](https://agentsforhumans.devpost.com/), [official rules](https://agentsforhumans.devpost.com/rules), and [FAQ](https://agentsforhumans.devpost.com/details/faqs). The overview's deliverables map to this evidence:

| Item | Evidence / remaining work |
|---|---|
| Strands project | Implemented; real Bedrock API acceptance recorded |
| Public source, MIT/Apache, README | Public MIT verified; final reviewed source includes setup and assets |
| Architecture diagram | PNG/SVG included in final source; PNG attached to draft |
| English project description | Draft saved in Devpost; final submission pending |
| Public video, maximum five minutes, working demo and pitch | Script ready; recording/upload/link unverified |
| AWS Builder ID | Verified profile email saved in draft; final submission pending |
| One track | Good Neighbor Agents saved and verified in the draft |
| Working test access | HTTPS healthy; fresh browser run and replay instructions need final validation |

Rules sections 1–5 require timely submission, eligibility, ownership/disclosures, functional access through October 8, and accurate materials. Deadline: **September 14, 7 PM Chicago**. Owner registration, team authority, rights and eligibility remain owner confirmations. Draft status is not submission proof. Post-deadline changes are restricted.

Sections 6–15 cover judging, IP/publicity permissions, prizes/taxes, releases, general conditions, disputes, incorporated terms and privacy. Those are participation terms, not coding tasks; review them before final submission. Eligibility includes age, residence and conflict-of-interest restrictions, which repository checks cannot establish.

AgentCore, a live-demo bonus, and Builder Center posts are optional scoring opportunities. Do not delay required materials for optional architecture work. Our internal 22-scenario evaluation and recovery checks are separately open product gates, not named submission deliverables.

## Remaining order before submission

1. Confirm owner registration, Builder ID and actual submission form status now.
2. Finish one real browser-driven run and record the demo while the exact candidate works.
3. UI deployment and public browser smoke check are complete; publish the matching final reviewed source, diagram and instructions.
4. Upload the public video, add source/demo/diagram/description and testing instructions to Devpost, then verify final submitted status before the deadline.
5. Keep the hosted service and owner-funded inference available during judging. A passing health check today is not proof of future availability.

The audit itself performed no deployment or inference. The later owner-authorized UI deployment is recorded in the [release receipt](evaluations/2026-09-14-ui-release.md). No public reset or final account submission was performed. See [finish-review evidence](evaluations/2026-09-14-finish-review.md) for the prior test results and open release gates.
