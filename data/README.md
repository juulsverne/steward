# Foundation fixtures

All entries are invented demo data. No real resident identity, district authority, municipal record, image inspection, or dispatch is established here.

- `signals.json` contains two independent seeded authors and original sample reports. The first image digest is **placeholder image-presence metadata**, not a hash of an actual photo. It exercises scoring only; it cannot be used as completion proof or evidence of a successful vision spike. Real before/middle/after images and their rights/provenance still need to be obtained.
- `policy.yaml` uses JSON-compatible YAML so the standard-library loader needs no extra dependency. The foundation command validates it against the locked implemented scoring rules; it is not a dynamic policy editor. Initial geocode precision is at most 30 meters, a demo parameter awaiting the fixture spike. The harness supplies 10 meters as a seeded accuracy fact; it performs no geocoding or geographic-authority check.
- Source-author IDs are canonical demo identities across channels. Unknown identity adds no independent-source points. Same author, normalized exact text, identical image digest, or shared repost lineage groups observations conservatively. This does not solve identity fraud, paraphrased copies, perceptual-image reuse, or semantic issue matching.
- Observation and receipt timestamps are separate, timezone-aware seeded values. The harness directly supplies the issue linkage. It does not claim model-selected matching or an intentional wait.

Run from the repository root: `uv run python -m agent.foundation --db .steward/foundation.sqlite3`. Existing destination files are refused; choose a fresh filename to repeat. The database contains the actual stored inputs, components, and append-only events from that run. Full demo reset/seed and real image assets belong to subsequent slices.
