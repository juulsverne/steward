# Supplemental synthetic evaluation images

These six images were generated on September 13, 2026 with the built-in image_gen tool. They are not photographs of real incidents. The generation model identifier was not provided and remains unknown. Exact generation instructions are retained in [PROMPTS.md](PROMPTS.md); expected visual conditions and filenames belong to evaluation provenance, not model input.

All six passed independent visual review against the generation brief. This establishes usable visible fixture conditions only. No Bedrock inspection, qualification result, policy score or end-to-end scenario pass is claimed by this catalog.

| Image | Visible condition accepted in review |
|---|---|
| persistence-later.jpg | Same brown couch and three bags from a visibly different viewpoint and lighting |
| ambiguous-before.jpg | Opaque van hides the entire couch area; target presence is unknown |
| mixed-hazard.jpg | A cable visibly connects damaged pole hardware to the couch/bag work area; energization and ownership are unknown |
| holdout-before.jpg | Separate blue couch and four boxes beside a brick wall and planting bed |
| holdout-partial.jpg | Blue couch removed; all four boxes remain |
| holdout-complete.jpg | Blue couch and all four boxes removed; work area clear |

The final three images share one distinct scene and form two comparison pairs with the same before image. They are not three independent scenes. If used to tune prompts, later use is regression coverage rather than unseen qualification.

The manifest records each published JPEG's SHA256, dHash, byte size and dimensions, plus the SHA256 of its retained original generated PNG. The fixed normalization profile is RGB JPEG quality 85, maximum side 1024, using the reviewed application helper at commit `51e8da2`; dHash is computed from final stored JPEG pixels. Original generated PNGs are retained locally. An original and its normalized encoding are one generated asset.

The original five-image catalog and its four-pair × three-repeat (12 inspection) result remain separate and unchanged. These new images do not increase that denominator. A later-observation scenario must separately supply honest synthetic reporter and capture-time metadata; neither the image nor its hash establishes 24 hours of elapsed real time. GPS and timestamps remain consistency evidence rather than real-world attestation.

Runtime inspection must receive only actual bytes, opaque evidence IDs and legitimate saved target/work-area facts. Do not include these filenames, prompts, table conditions, manifest roles, expected scores or scenario answers in model requests. Known raw and normalized hashes are a trusted provenance registry; users cannot choose provenance by submitting labels.
