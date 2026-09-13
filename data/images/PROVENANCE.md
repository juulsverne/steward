# Synthetic demo images

Generated September 13, 2026 with the built-in OpenAI image-generation tool. The tool did not report its underlying model version. These are invented scenes, not photographs of a real incident or the actual facade at 1530 S Michigan Ave. That address is only a seeded demo anchor. No third-party source photograph was supplied.

The four generated PNGs were inspected visually, then normalized to metadata-free RGB JPEG with a longest side of 1024 pixels at quality 85. `reused.jpg` is a quality-60 re-encode of `after.jpg`, intentionally representing recycled completion evidence. Synthetic provenance remains explicit here and in the manifest even though embedded image metadata is removed. No claim of production fraud detection or real GPS/capture-time attestation is made.

| File | Origin | Intended condition |
|---|---|---|
| before.jpg | Text generation | Couch and three black bags obstruct sidewalk |
| middle.jpg | Edit of before | Couch removed; bags and litter remain |
| after.jpg | Edit of before | Couch, bags, litter removed; work area clear |
| unrelated.jpg | Separate text generation | Different plaza, bike rack, glass building |
| reused.jpg | Re-encode of after | Prior completion photo reused despite different file bytes |

Usage provenance: generated for this project from original prompts and generated references. Provider terms govern usage; publication-rights review remains in the submission checklist. Raw generator outputs remain local. Public fingerprints are in `manifest.json`; `consistency.json` contains separately labeled seeded coordinates/times.

## Exact prompts

### before

Create one photorealistic synthetic demo photograph, landscape 4:3. Phone camera at eye level on a Chicago South Loop inspired sidewalk on an overcast morning. A large worn brown three-seat fabric couch sits abandoned on the concrete sidewalk beside a black iron fence and a parkway tree. The couch is prominent in the middle foreground, occupying about one third of image width. Three large stuffed black trash bags are clearly visible beside it, taking up the foreground sidewalk, plus a few paper scraps. Mid-rise brick building in background and parked cars on street. No people, no readable signs, no logos, no overlay text. Realistic slightly grainy documentary photo. The invented scene will be used as the BEFORE image in a cleanup demonstration; the couch and bags must be unambiguously visible. Preserve a clear consistent viewpoint suitable for later edits removing the couch and trash. Do not depict an identifiable actual address.

### middle

Edit this synthetic demo photograph. Remove only the brown couch completely, revealing the concrete sidewalk behind it. Keep all three large black trash bags exactly where they are at the lower left, and leave the paper litter beside them. No new sharp debris, glass, wires or spills. Preserve the exact camera viewpoint, framing, dimensions, brick buildings, iron fence, tree, parked cars, overcast lighting, colors and every other scene feature. No people or overlay text. This is a partial cleanup: couch removed but conspicuous bags remain.

### after

Edit this synthetic demo photograph. Remove the entire brown couch, all three black trash bags, and all paper litter or loose debris in the foreground sidewalk work area. Reveal clean clear concrete paving in their places. Preserve the exact camera viewpoint, framing, dimensions, buildings, black iron fence, tree, parked cars, overcast lighting, color and all permanent scene features. No people or overlay text. The entire sidewalk work area must be visibly clean and free of objects, trash and hazards.

### unrelated

Create one photorealistic synthetic demo photograph, landscape 4:3. Phone camera at eye level of a city pedestrian plaza with a bike rack and modern bus shelter, glass office tower behind, broad pale stone pavement, bright sunny afternoon. No couch, no trash, no people, no text overlays or readable signs. Different from a residential brick-building sidewalk: this is an unrelated scene used as a negative verification fixture.
