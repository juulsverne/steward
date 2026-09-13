# PRD adversarial review — September 12, 2026

Cara requested a more substantial product document and an adversarial review by Fable 5.1. The primary editor expanded the PRD while the independent reviewer examined the prior version and its supporting specifications. Recommendations were reconciled against Cara's canonical plan, not adopted automatically.

## Review provenance

- Mechanism: local `/Users/cara/.local/bin/claude -p`.
- Requested and reported substantive model: `claude-fable-5-1`.
- Initial review effort: high; successful one-turn review, no model fallback configured.
- The first attempt failed because Claude Code 2.1.207 did not support the model. The CLI was updated to 2.1.269 and the same model was retried successfully.
- Revised-doc consistency check: same model, medium effort; completed successfully. Fable reported no release-blocking documentation contradictions, while explicitly retaining unresolved build/product decisions.

This is a documentation review, not customer validation, runtime testing, a security audit, or the project evaluation. Reviewer text does not establish implemented behavior.

## What changed in the product document

The expanded [PRD](PRD.md) explains the product definition, hypothesized coordination problem, buyer and stakeholder value, product principles, conceptual objects, user responsibilities, scope, complete couch journey, surface behavior, autonomy boundaries, failure behavior, requirement traceability, success measures, truth labels, open gates, and post-competition direction.

The thirteen requirement IDs and sixteen demo acceptance steps remain intact. The expanded narrative adds product meaning and testable behavior without turning the company vision into the weekend backlog.

## Findings and disposition

| Finding | Disposition |
|---|---|
| Thin problem/buyer/value explanation | Added an explicit product story and before/after coordination model; labeled customer claims as hypotheses |
| Missing conceptual objects and inconsistent vocabulary | Defined Signal, Issue, official record, evidence, plan, job, exception, settlement, and event; clarified key UI/state labels |
| Unknown resident identity cannot support mandatory independent corroboration | Acceptance fixtures use explicitly distinct seeded author IDs and original observations; anonymous requests do not become verified witnesses |
| First 65 points can become 80 after early service lookup | Remains an explicit unresolved spike gate; no concealed record, forced arithmetic, or unapproved retrieval restriction |
| Upload time does not establish newer physical evidence | Require observation/capture provenance, separate receipt time, and a fixture manifest |
| Clean before-and-after images could authorize unperformed removal | Added nullable `target_present_before` as a verification prerequisite, with no new score component; absent/unknown target goes to unpaid review |
| Mixed prohibited hazard can be lost under a benign category | Preserve hazard evidence and block ordinary autonomous cleanup |
| Rework scope and economics are unstated | Same work scope, job, quote, and reservation; no second dispatch charge |
| Reservation accounting and cancellation unclear | State budget effect at dispatch/payment; unpaid cancellation releases its reservation once, without requiring a cancellation UI |
| Stale decisions or new proof during a pending exception | Bind exception to proof; reject stale decisions; V1 accepts new completion submissions only after check-in or requested rework; retries stay idempotent |
| Manual inspection implies an unbuilt workflow | Define an open operator hold; existing Request completion can resume when appropriate; no manual Verified/Paid button |
| Actor binding deferred to sign-in choice | Enforce assigned-vendor/operator context under either access mode; demo switching changes acting persona |
| Live data cannot guarantee the historical couch contradiction | Explicit labeled demo-data mode and fixed manifest for acceptance; live runs expose their actual results |
| Verification sounds like independent inspection | State that it evaluates provider-supplied proof and consistency checks with known limits |
| New report after resolution could disappear into a closed issue | Preserve/investigate it; review is permitted, while automatic reopening/recurrence workflows remain out of required scope |

## Recommendations intentionally not adopted

- **Require different channels for independence.** Two distinct original observers can use the same resident form; channel difference alone proves nothing.
- **Use upload order to award capture-time verification points when capture time is unknown.** That would weaken the freshness claim; uncertain proof must remain uncertain.
- **Replace the twenty-case evaluation with acceptance counts only.** The canonical evaluation compares plain Sonnet and Steward on the specified error metrics. Workflow acceptance remains a separate validation activity.
- **Relax the explicit denied-payment-tool demo step.** The locked demo includes a real denied authorization request. It must not be fabricated or silently removed.
- **Automatically create linked recurrence issues after resolution.** That adds behavior beyond the required couch proof; preserving the new signal for investigation/review is sufficient for V1.
- **Introduce extra user questions for every edge case.** Routine bounded lifecycle behavior is documented directly; only actual unresolved product/authority choices stay open.

## Remaining uncertainty

The first-signal lookup conflict and actual vision performance remain build gates. Real sign-in versus demo access, payment-exception permission, and resident follow-up are unapproved product choices. The new prerequisite and failure cases need meaningful implementation tests; prose alone does not validate them.

## Revised-document check and final corrections

The second pass reviewed the expanded PRD, architecture, and agent contract. It confirmed consistent scoring, reservation accounting, proof-submission rules, fixture labels, and the explicit denied-settlement request. Its remaining wording findings were addressed:

- Scoped alternate issue states so an official-record dispute or active-job payment exception cannot erase the couch workflow state.
- Declared condition-not-found an unpaid operator investigation hold outside the required path; did not invent a cancellation screen or removal work for an absent target.
- Limited demo actor guarantees to server-side consistency, not authentication of an actual provider employee.

Local checks confirmed Markdown links, retained PR-01 through PR-13 IDs, all sixteen demo steps, and clean diff whitespace. No runtime tests were run for these documentation changes. The independent review does not resolve the first-signal scoring conflict or prove Bedrock vision performance.
