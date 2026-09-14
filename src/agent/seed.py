"""Create or explicitly replace one labeled local Steward demo database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from . import contracts as c
from .images import NormalizedImage, dhash
from .intake import POLICY_VERSION, community_signal, persist_signal
from .store import Store

SEED_VERSION = "south-loop-demo-b3"


def _under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _has_symlink_component(path: Path) -> bool:
    current = path
    while current != current.parent:
        if current.is_symlink():
            return True
        current = current.parent
    return current.is_symlink()


def _seed(path: Path, data: Path, scenario: str = "baseline") -> dict:
    from .adapters import FIXTURE_SCENARIOS, fixture_service_record
    if scenario not in FIXTURE_SCENARIOS:
        raise ValueError("unknown fixture scenario")
    feed = json.loads((data / "feed.json").read_text(encoding="utf-8"))
    manifest_bytes = (data / "images" / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    before = data / "images" / manifest["images"]["before"]["file"]
    image_bytes = before.read_bytes()
    image = NormalizedImage(image_bytes, hashlib.sha256(image_bytes).hexdigest(), dhash(before))
    if image.image_sha256 != manifest["images"]["before"]["sha256"]:
        raise ValueError("seed image does not match reviewed manifest")
    first = community_signal(feed["posts"][0], image=image)
    staged = json.loads((data / "signals.json").read_text(encoding="utf-8"))[1]
    actor = c.ActorContext(actor_id="steward-service", actor_type="service", label="Steward",
                           district_id="south_loop_demo")
    with Store(path) as store:
        context = c.MutationContext(actor=actor, operation="ingest_source", idempotency_key="seed-feed-1")
        persist_signal(store, signal=first, context=context, image=image,
                       image_root=path.parent / "images", provenance="synthetic")
        store.create_issue("demo-couch", "bulky_waste", "1530 S Michigan Ave")
        # The original intake event remains issue-less. Linking and trusted cause
        # binding form one transaction, exactly as the real intake transition does.
        from .investigation import _bind_unlinked_signal_invocation
        invocation = store.invocation_for_event(store.get_signal_receipt(first.id).event_id)
        with store.transaction() as tx:
            store._link_signal("demo-couch", first.id)
            _bind_unlinked_signal_invocation(tx, store,
                context.model_copy(update={"invocation_id": invocation.id}),
                signal_id=first.id, issue_id="demo-couch")
        from .adapters import SeededAdapters
        from .investigation import record_geocode
        record_geocode(store, issue_id="demo-couch", signal_id=first.id,
            result=SeededAdapters(data).geocode(first),
            context=c.MutationContext(actor=actor, operation="geocode_location",
                idempotency_key="seed-geocode-1",
                expected_revision=store.get_issue_record("demo-couch").state_revision))
        record = fixture_service_record(data, scenario)
        store.record_service_match("demo-couch", record)
        vendors = json.loads((data / "vendors.json").read_text(encoding="utf-8"))
        with store.transaction() as tx:
            for vendor in vendors:
                payload = {**vendor, "service_categories": tuple(vendor["service_categories"]),
                    "service_area": tuple(vendor["service_area"]),
                    "equipment": tuple(vendor["equipment"]), "seed_version": SEED_VERSION}
                tx.insert_vendor(c.VendorRecord(**payload))
            tx.insert_budget(c.BudgetRecord(id="south_loop_demo", initial_cents=50000,
                                             policy_version=POLICY_VERSION))
        receipt = c.SeedReceipt(id="south-loop-demo-seed", seed_version=SEED_VERSION,
            policy_version=POLICY_VERSION, fixture_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            baseline_signal_id=first.id, staged_signal_id=staged["id"], created_at=datetime.now(UTC), scenario=scenario)
        store.save_seed_receipt(receipt)
        score = store.get_issue("demo-couch")["evidence_score"]
    expected_score = 80 if scenario == "couch-open-one-v1" else 65
    if score != expected_score:
        raise RuntimeError(f"seed baseline score must be {expected_score}, got {score}")
    return {"database": str(path), "seed_version": SEED_VERSION, "baseline_score": score,
            "baseline_signal": first.id, "staged_second_report": staged["id"],
            "fixture_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "scenario": scenario}


def _is_marked_demo(path: Path) -> bool:
    """Authorize reset without migration, initialization, or any write to the existing target."""
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        db = sqlite3.connect(uri, uri=True)
        try:
            row = db.execute("SELECT record_json FROM seed_receipts WHERE id=?",
                             ("south-loop-demo-seed",)).fetchone()
        finally:
            db.close()
        return row is not None and c.SeedReceipt.model_validate_json(row[0]).seed_version == SEED_VERSION
    except (OSError, sqlite3.DatabaseError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(".steward/steward.sqlite3"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--scenario", choices=("baseline", "couch-open-one-v1"), default="baseline")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    requested = Path(os.path.abspath(args.db))
    root_requested = Path(os.getenv("STEWARD_DEMO_ROOT", str(requested.parent))).absolute()
    destination = requested.resolve()
    root = root_requested.resolve()
    if (requested.suffix != ".sqlite3" or _has_symlink_component(requested)
            or _has_symlink_component(root_requested) or not _under_root(destination, root)
            or destination == root):
        parser.error("--db must be a named .sqlite3 file under the configured demo root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not args.reset:
            parser.error("database already exists; use --reset only for a marked demo database")
        if not _is_marked_demo(destination):
            parser.error("--reset refuses an unmarked or invalid database")
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp.sqlite3")
    try:
        result = _seed(temporary, args.data.resolve(), args.scenario)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    result["database"] = str(destination)
    result["reset"] = args.reset
    print("OFFLINE DEMO SEED - labeled simulated fixtures; no live municipal, model, or dispatch action")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
