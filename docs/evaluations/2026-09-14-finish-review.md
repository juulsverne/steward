# Finish review and original design restoration, September 14

Status: local integration and review. The public deployment remains application commit `57e7e27`; these changes have not been pushed or deployed.

The continuation combined the three unfinished work streams on `codex/finish-review`: UI `4480478`, hosting `7c456a8`, and materials `6c76d70`, starting from local main `e74b0d0`. Existing untracked settings and earlier acceptance databases were preserved.

## Reliability repairs

- Deployment packaging now builds the frontend and deploy files from the selected committed revision, creates its output directory, and finishes preparation before provisioning cloud resources.
- Teardown stops writes, requires successful backup completion, downloads the exact backup, and verifies its manifest/checksums before termination or volume deletion. Failure preserves the instance and volume with the service stopped for inspection. Teardown was not executed.
- Persona changes clear prior actor content and fail closed when identity is uncertain. Late session reads cannot cancel a persona change's confirmation.
- Proof/report receipts and operator decisions remain visibly saved when status reads fail. Retry reads the receipt or invocation instead of repeating an acknowledged write.
- Check-in and upload retries retain the original request key/body/revision; explicit input corrections create a new attempt. Location callbacks cannot replace an in-flight check-in.
- Resource navigation cancels stale reads/polls; file inputs are contained on narrow screens.

Hosting repairs were authored by Astra high and independently reviewed by Astra high. Frontend repairs were authored by Terra high and reviewed by Astra high, including two bounded repair rounds. The lead reconciled documentation against the actual receipts; Terra high reviewed the materials.

## Verification in this continuation

| Check | Observed result |
|---|---|
| Locked Python dev/web install | Passed; corrected a missing `itsdangerous` dependency in the existing root environment |
| Backend full offline suite | **706 passed**, one upstream Starlette deprecation warning, 879.36 seconds |
| New deployment regressions | **10 passed**, including independent rerun; AWS and npm mocked |
| Python lint | Passed for `src`, `tests`, and `scripts` |
| Deployment Bash syntax | Passed |
| Frontend reliability suite | 67 passed before the final location-correction regression; final affected CrewJob checks: 8 passed; typecheck passed |
| Documentation links | 184 relative links resolved, zero broken before this report was added |
| Hosted read-only smoke | Public health 200; browser Board and Issue Detail displayed the resolved couch, rejected 90-point proof, accepted 100-point proof and one simulated $72 settlement |
| Local browser regression | Before repair, switching South Loop crew to Windy City retained South Loop's job; after repair, Windy City showed no assigned jobs |

No new Bedrock invocation, cloud mutation, hosted reset, or settlement was performed in this continuation. Local browser checks used copies of retained acceptance databases and images, with runtime execution disabled. Those checks do not constitute a fresh live couch run.

## Design restoration

The owner requested restoration of the original September 13 civic study during this review. Its direction is warm paper surfaces, navy text, restrained teal/amber, Newsreader display headings, Public Sans interface text, large paired evidence images, fine dividers and a narrow decision/work-order column. The application must use its real API evidence and policy results; the study's simulated actions are not application behavior.

Visual implementation and final browser verification are recorded below when complete.

## Gates still open

The retained earlier UI walk is API-driven acceptance plus rendered-state inspection. It does not establish a complete browser-driven P7 run and repeat. The 22-scenario evaluation, hosted criterion 16, instance replacement, backup restoration and unfinished-work recovery remain unverified. AgentCore Runtime, Observability and Gateway remain undeployed. Public video and final submission verification remain separate release work.
