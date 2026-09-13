"""Run explicitly offline fixture checks; never presented as a live agent demo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import Signal
from .store import POLICY_VERSION, PRECISE_GEOCODE_MAX_M, Store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(".steward/foundation.sqlite3"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args()
    policy = json.loads((args.data / "policy.yaml").read_text(encoding="utf-8"))
    if policy != {
        "version": POLICY_VERSION, "district": "south_loop_demo", "provenance": "seeded",
        "actionable_min_score": 70, "precise_geocode_max_m": PRECISE_GEOCODE_MAX_M,
        "image_points": 30, "independent_source_points": 20, "independent_source_cap": 2,
        "precise_geocode_points": 15, "service_match_points": 15,
    }:
        parser.error("policy fixture differs from implemented foundation policy")
    signals = [Signal.from_dict(row) for row in json.loads(
        (args.data / "signals.json").read_text(encoding="utf-8")
    )]
    if len(signals) != 2 or any(signal.provenance != "seeded" for signal in signals):
        parser.error("foundation check requires the two labeled seeded observations")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive creation prevents overwriting any existing database or other file.
        with args.db.open("xb"):
            pass
    except FileExistsError:
        parser.error("database already exists; choose a new --db path (no automatic deletion)")
    print("OFFLINE FOUNDATION CHECK — seeded metadata; no Strands, vision, or agent decisions")
    issue_id = "demo-couch"
    with Store(args.db) as store:
        store.create_issue(issue_id, "bulky_waste", "1530 S Michigan Ave")
        store.record_geocode(issue_id, accuracy_m=10, provenance="seeded")
        first = store.add_signal(issue_id, signals[0])
        print(json.dumps({"phase": "first_signal", "score": first["score"]}))
    with Store(args.db) as resumed:
        second = resumed.add_signal(issue_id, signals[1])
        print(json.dumps({"phase": "second_signal_after_reopen", "score": second["score"]}))
        print(json.dumps({"status": second["status"], "events": resumed.events(issue_id)}))
    if first["evidence_score"] != 65 or second["evidence_score"] != 85:
        raise RuntimeError("foundation fixture scores differ from the expected 65/85")
    print(f"Persisted: {args.db.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
