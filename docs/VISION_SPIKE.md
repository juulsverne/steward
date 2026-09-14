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

## Requalification after the completion hazard definition — September 14, 2026

During the B13 live acceptance the middle proof (couch removed, bags remaining) scored 90 in one run and 80 in the next because the inspector once reported the leftover bags as a "new hazard". The `no_new_hazard` field and the system prompt now define a new hazard as one introduced by the work (exposed wires, broken glass, spills, fire); bags, litter or debris already present that remain are not new hazards and only affect `area_clear`. Prompt version `cea02b88fbad2ce3`; findings schema `6d1d3b188972ac46`.

Rerun alone at `2026-09-14T07:36:29Z` with the same model, region and three repeats: **12/12 expected outcomes, zero errors, zero false acceptances** (`.steward/vision-spike-20260914T073629760499Z.json`). Middle 90/90/90 with prerequisites passed and no automatic payment; after 100/100/100 eligible; unrelated 40/40/40 with `same_scene`, `target_removed`, `no_new_hazard` and `area_clear` failed; reused 100/100/100 blocked by `image_reuse`. Latencies 6.5–7.5 s. An earlier attempt at `07:33:59Z` recorded one `ThrottlingException` on the reused pairing because a live acceptance run was executing concurrently; the runtime disables SDK retries, so Bedrock workloads must run one at a time.

## Reproduce

```powershell
uv run --no-sync python -m agent.bedrock_check
uv run --no-sync python -m agent.vision_spike --images data/images --repeats 3
```

Use an authenticated AWS profile. The preflight must pass first. The spike serializes inspections with at least seven seconds between starts by default, checkpoints every result, and writes a unique artifact. Any error, unexpected outcome/score, false acceptance, missed full-cleanup acceptance, incomplete run, or fewer than three repeats fails its gate.

The fixture-specific Tier 1A verification gate is closed. The event API, dispatch/settlement state, Strands HTTP tools, crew/operator resume, and complete couch acceptance flow remain to be built and verified.
