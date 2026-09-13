# Vision spike — passed September 13, 2026

The live Tier 1A gate passed: **12/12 expected outcomes, zero model errors, zero false automatic acceptances**. This is a small synthetic-fixture stability check, not the twenty-two-scenario evaluation or the sixteen-step live couch demo.

Model: `global.anthropic.claude-sonnet-4-6` in `us-west-2`; temperature 0; maximum 1024 output tokens per inspection; prompt version `51ffbcab39ca79c3`. Run started `2026-09-13T07:11:12.440695+00:00`. Each comparison used one bounded Converse request, without constructing a second agent.

Raw artifact: `.steward/vision-spike-20260913T071112411178Z.json` (local/ignored). It contains the exact system prompt, target/work area, image digests, seeded consistency inputs, structured model outputs, request IDs, usage, timings, and prerequisite results.

| Pairing | Runs | Errors | Prerequisites passed | Eligible for payment | False accepts | Expected outcomes | Scores |
|---|---:|---:|---:|---:|---:|---:|---|
| before → middle | 3 | 0 | 3 | 0 | 0 | 3/3 | 90, 90, 90 |
| before → after | 3 | 0 | 3 | 3 | 0 | 3/3 | 100, 100, 100 |
| before → unrelated | 3 | 0 | 0 | 0 | 0 | 3/3 | 40, 40, 40 |
| before → reused | 3 | 0 | 0 | 0 | 0 | 3/3 | 100, 100, 100 |

Eligibility is a deterministic result, not a payment action. All reused-image runs had raw score 100 but were blocked by the reuse prerequisite.

## Strands prerequisite

After the user refreshed AWS login, the preflight passed at `2026-09-13T07:10:54Z`: `current_time` was requested, its successful result returned to Sonnet, and a final `end_turn` reply arrived in two model cycles. Latency 2.678 s; usage 1,809 input and 76 output tokens. Artifact: `.steward/bedrock-check-20260913T071054517582Z.json`.

The earlier failed attempt (`LoginRefreshRequired`, zero tool calls) is retained at `.steward/bedrock-check-20260913T070246827959Z.json`. The installed community `current_time` tool emitted a deprecation warning; it is used only by this preflight, not registered as a Steward operations tool.

## Fixtures and consistency

See [provenance and exact generation prompts](../data/images/PROVENANCE.md), [fingerprints](../data/images/manifest.json), and [seeded consistency inputs](../data/images/consistency.json).

- Reused→after dHash distance **1** (threshold **6**); file SHA-256 values differ.
- Fresh after→prior middle dHash distance **7**; no reuse detected. The one-bit margin limits confidence for recompressed/cropped variants.
- Before is excluded from every reuse comparison. The clear rework image was checked against the failed middle proof.
- Seeded check-in distance is about **8.90 m** and after-observation times are later than before. These are computed consistency checks, not GPS/capture-time attestation.
- Scene and condition are invented; association with the seeded address does not make them real incident photographs.

## Unknown findings and limitations

All three unrelated-scene runs returned `same_scene: false` and `null` for `target_removed`, `no_new_hazard`, and `area_clear`. These unknowns correctly blocked prerequisites; none authorized payment. Positive cleanup runs returned no unknown findings. No model-call errors occurred.

Bag-count descriptions varied between two and two-to-three; the required presence/clearance findings still matched. This check does not evaluate exact object counting. Three repetitions of generated images do not establish production reliability; crops, rephotographed prints, challenging lighting, and additional locations were not tested.

Median observed inspection latency: **6.513 s**. Total image-run usage: **38,388 input / 3,907 output tokens**. These are actual usage counts, not a dollar-cost estimate.

## Reproduce

```powershell
uv run --no-sync python -m agent.bedrock_check
uv run --no-sync python -m agent.vision_spike --images data/images --repeats 3
```

Use an authenticated AWS profile. The preflight must pass first. The spike serializes inspections with at least seven seconds between starts by default, checkpoints every result, and writes a unique artifact. Any error, unexpected outcome/score, false acceptance, missed full-cleanup acceptance, incomplete run, or fewer than three repeats fails its gate.

The fixture-specific Tier 1A verification gate is closed. The event API, dispatch/settlement state, Strands HTTP tools, crew/operator resume, and complete couch acceptance flow remain to be built and verified.
