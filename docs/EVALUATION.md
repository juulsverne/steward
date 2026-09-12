# Small internal evaluation

Status: planned, no results yet. Compare plain Sonnet with Steward using the same model version and twenty frozen, labeled scenarios. This is a small internal evaluation, not a scientific benchmark.

## Scenario set

1. Single couch signal: watch at 65.
2. Independent corroboration: actionable at 85.
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

## Fair comparison and logging

Freeze expected route, merge outcome, authorized action, and escalation requirement before runs. Give both conditions the same operating policy and structured response schema. Plain Sonnet receives a single request with the initial scenario context and has no retrieval, tools, or persisted workflow. Steward starts with that same initial context and may retrieve the scenario's supporting facts through tools. Report this information-access difference explicitly: the comparison evaluates the whole system, not an isolated model improvement.

Use the same image assets where the initial input contains images. Record exact prompts, model ID, configuration, fixtures, outputs, tool traces, errors, and latency. Missing facts should allow the baseline to abstain. Score proposed actions for both conditions, and separately record which forbidden actions Steward's policy actually blocked. Never compare baseline recommendations to Steward executed actions as if they were the same measure.

## Metrics

| Metric | Definition |
|---|---|
| Routing accuracy | Correct responsibility route / route-labeled scenarios |
| False merge rate | Distinct-condition pairs incorrectly merged / labeled distinct-condition pairs |
| Incorrect autonomous action rate | Scenarios proposing unauthorized dispatch/payment/closure / action-labeled scenarios; separately report executed violations |
| Unnecessary escalation rate | Fully specified, autonomously solvable scenarios escalated / labeled autonomously solvable scenarios |

Publish numerator and denominator, per-case results, tool errors, and material limitations; percentages alone hide the small sample. Report legitimate abstention separately. Twenty scenarios do not support broad reliability claims. If time permits repeats, apply the same repeat count to both conditions and retain every run. Never backfill plausible-looking scores for the video.
