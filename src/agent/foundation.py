"""Run explicitly offline fixture checks; never presented as a live agent demo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import Signal
from .policy import load_policy
from .store import Store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(".steward/foundation.sqlite3"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    args = parser.parse_args()
    try:
        load_policy(args.data / "policy.yaml")
    except ValueError as exc:
        parser.error(str(exc))
    signals = [Signal.from_dict(row) for row in json.loads(
        (args.data / "signals.json").read_text(encoding="utf-8")
    )]
    if len(signals) != 2 or any(signal.provenance != "seeded" for signal in signals):
        parser.error("foundation check requires the two labeled seeded observations")
    records = json.loads((args.data / "service_records.json").read_text(encoding="utf-8"))
    if len(records) != 1 or records[0]["status"] != "COMPLETED":
        parser.error("foundation check requires the one seeded COMPLETED service record")
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
        store.create_issue(issue_id, "bulky_waste", "State St & Madison St (demo)")
        store.record_geocode(issue_id, accuracy_m=10, provenance="seeded")
        first = store.add_signal(issue_id, signals[0])
        print(json.dumps({"phase": "first_signal", "score": first["score"]}))
        pending = store.record_service_match(issue_id, records[0])
        print(json.dumps({
            "phase": "completed_record_pending", "score": pending["score"],
            "conflict": pending["service_record"]["conflict"],
        }))
    with Store(args.db) as resumed:
        second = resumed.add_signal(issue_id, signals[1])
        print(json.dumps({"phase": "second_signal_after_reopen", "score": second["score"]}))
        disputed = resumed.confirm_official_dispute(issue_id)
        print(json.dumps({
            "phase": "dispute_confirmed", "score": disputed["score"],
            "conflict": disputed["service_record"]["conflict"],
        }))
        print(json.dumps({"status": disputed["status"], "events": resumed.events(issue_id)}))
    totals = [x["evidence_score"] for x in (first, pending, second, disputed)]
    if totals != [65, 65, 85, 100]:
        raise RuntimeError(f"foundation fixture scores {totals} differ from the expected 65/65/85/100")
    print(f"Persisted: {args.db.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
