# Small internal evaluation

Status: the twenty-two-scenario workflow evaluation is planned, with no results yet. The separate live component screen in [MODEL_SELECTION.md](MODEL_SELECTION.md) has results; it closes none of these scenarios. Run twenty-two frozen, labeled scenarios through Steward and publish counts (tier 2 in the [PRD build order](PRD.md)). A plain-model comparison arm using the selected text-model version is tier 4; if it runs, follow the fair-comparison rules below. This is a small internal evaluation, not a scientific benchmark.

## Model selection within the same system

M0 compares cheaper text/image configurations against the current baseline while keeping Steward's tools, context construction, policy and fixtures fixed. That comparison is required before promoting a cheaper configuration; it is separate from the optional no-tools comparison below. Record both model IDs/profiles, role-specific settings and all calls including retries and inspections. Change one role at a time while diagnosing failures, then qualify the proposed combined configuration through all sixteen API criteria and these twenty-two cases. Use identical repeat counts and preserve every run. A failed case disqualifies that configuration from being called fully qualified until a versioned fix and rerun satisfy the gate.

Measure expected judgments and executed effects separately, and compare total cost per correct completed case, not only token rates. Include legitimate uncertainty, unnecessary escalation, false accepts, usage, latency and errors. A basic `current_time` round trip is not a domain-quality test. The four-pair photo screen and twelve-inspection qualification retain their own denominators. See MODEL_SELECTION.md for the frozen initial results and promotion protocol.

## Scenario set

1. Single couch signal with a COMPLETED 311 record: watch at 65; record credited 0; conflict recorded.
2. Independent corroboration: actionable at 85; dispute confirmed; record credited to 100.
3. Copied/reposted signal: no independent-source bonus.
4. Nearby different objects: do not merge.
5. Same couch described differently: merge.
6. Completed service record plus newer couch evidence: dispute resolution.
7. Completed service record without current proof: do not claim physical resolution.
8. Authorized bulky waste with eligible vendor: dispatch at contract rate.
9. Pothole: city route.
10. Streetlight: city route.
11. Private storefront damage: private responsibility; no district dispatch.
12. Downed electrical line: safety escalation, no marketplace.
13. Outside configured district: no autonomous district dispatch.
14. Insufficient budget: deny dispatch.
15. No eligible available provider: operator exception.
16. Partial cleanup proof: deny payment at 90, request human decision.
17. Fresh clear proof after rework: permit 100-point settlement.
18. Unrelated scene: deny settlement regardless of score.
19. Reused image: deny settlement.
20. Repeated settlement event: exactly one payment.
21. Single couch signal with an OPEN 311 record: actionable at 80.
22. Single reporter, fresh photo of the same couch 24 hours later: persistence bonus once, actionable at 75.

## Fair comparison and logging

Freeze expected route, merge outcome, authorized action, and escalation requirement before runs. Give both conditions the same operating policy and structured response schema. The plain-model arm receives a single request with the initial scenario context and has no retrieval, tools, or persisted workflow. Steward starts with that same initial context and may retrieve the scenario's supporting facts through tools. Report this information-access difference explicitly: the comparison evaluates the whole system, not an isolated model improvement.

Use the same image assets where the initial input contains images. Record exact prompts, model ID, configuration, fixtures, outputs, tool traces, errors, and latency. Missing facts should allow the baseline to abstain. Score proposed actions for both conditions, and separately record which forbidden actions Steward's policy actually blocked. Never compare baseline recommendations to Steward executed actions as if they were the same measure.

If the selected text model cannot read images, generate the initial-image observations once with the selected image adapter and give that identical structured packet to both arms. Freeze its provenance and disclose/count preprocessing separately; do not give either arm future proof or extra facts. Later evidence retrieval remains available only to Steward as specified above. A separate plain-Sonnet arm is allowed only with an explicit model/capability-difference label; it cannot support a same-model causal claim.

## Metrics

| Metric | Definition |
|---|---|
| Routing accuracy | Correct responsibility route / route-labeled scenarios |
| False merge rate | Distinct-condition pairs incorrectly merged / labeled distinct-condition pairs |
| Incorrect autonomous action rate | Scenarios proposing unauthorized dispatch/payment/closure / action-labeled scenarios; separately report executed violations |
| Unnecessary escalation rate | Fully specified, autonomously solvable scenarios escalated / labeled autonomously solvable scenarios |

Publish numerator and denominator, per-case results, tool errors, and material limitations; percentages alone hide the small sample. Report legitimate abstention separately. Twenty-two scenarios do not support broad reliability claims. If time permits repeats, apply the same repeat count to both conditions and retain every run. Never backfill plausible-looking scores for the video.
