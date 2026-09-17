"""Copy a quiescent Steward demo SQLite database to the public Loop demo anchor.

The source is opened read-only and is never changed. Stop the service and ensure
the source is quiescent for the whole copy: the status check cannot prevent a
new invocation from being queued after it runs. The destination must not already
exist. The script derives the legacy location and coordinates from the named
seeded issue, then updates only that location text, optional caller-supplied
aliases, and coordinate pairs within the requested radius of that anchor.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

PUBLIC_LOCATION = "State St & Madison St (demo)"
PUBLIC_LAT = 41.88206
PUBLIC_LON = -87.62780
EARTH_RADIUS_M = 6_371_000
ACTIVE_INVOCATION_STATUSES = ("PENDING", "RUNNING")


def _distance_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    lat_a, lon_a, lat_b, lon_b = map(math.radians, (lat_a, lon_a, lat_b, lon_b))
    sin_lat = math.sin((lat_b - lat_a) / 2)
    sin_lon = math.sin((lon_b - lon_a) / 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(sin_lat ** 2 + math.cos(lat_a) * math.cos(lat_b) * sin_lon ** 2))


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)


def _source_anchor(db: sqlite3.Connection, issue_id: str) -> tuple[str, float, float]:
    try:
        row = db.execute("SELECT location, geocode_json FROM issues WHERE id=?", (issue_id,)).fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError("source does not contain the required Steward issues table") from exc
    if row is None:
        raise ValueError(f"source does not contain seeded issue {issue_id!r}")
    try:
        geocode = json.loads(row[1])
        location, lat, lon = row[0], float(geocode["lat"]), float(geocode["lon"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("seeded issue needs a JSON geocode with finite lat/lon") from exc
    if not location or not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError("seeded issue needs a nonempty location and finite lat/lon")
    return location, lat, lon


def _derived_aliases(location: str) -> tuple[str, ...]:
    """Cover the seeded feed's short and expanded street prose without storing it."""
    words = location.split()
    aliases = [location]
    if len(words) >= 2:
        aliases.append(" ".join(words[:-1]))
    expanded = {"N": "North", "S": "South", "E": "East", "W": "West", "Ave": "Avenue", "St": "Street"}
    aliases.append(" ".join(expanded.get(word, word) for word in words))
    return tuple(sorted(set(aliases), key=len, reverse=True))


def _assert_quiescent(db: sqlite3.Connection) -> None:
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "invocations" not in tables:
        raise ValueError("source does not contain the required Steward invocations table")
    placeholders = ",".join("?" for _ in ACTIVE_INVOCATION_STATUSES)
    active = db.execute(
        f"SELECT id, status FROM invocations WHERE status IN ({placeholders}) ORDER BY id",
        ACTIVE_INVOCATION_STATUSES,
    ).fetchall()
    if active:
        ids = ", ".join(str(row[0]) for row in active[:5])
        raise ValueError(f"source has active invocation(s): {ids}; wait for them before relocation")


def _relocator(legacy_location: str, aliases: tuple[str, ...], old_lat: float, old_lon: float, radius_m: float):
    text_values = tuple(sorted(
        {alias for alias in (*_derived_aliases(legacy_location), *aliases) if alias},
        key=len,
        reverse=True,
    ))

    def replace_text(value: str) -> str:
        for legacy in text_values:
            value = value.replace(legacy, PUBLIC_LOCATION)
        return value

    def replace_coordinates(value: Any) -> tuple[Any, bool]:
        if isinstance(value, dict) and {"lat", "lon"} <= value.keys():
            lat, lon = value["lat"], value["lon"]
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and _distance_m(lat, lon, old_lat, old_lon) <= radius_m:
                updated = dict(value)
                updated["lat"], updated["lon"] = PUBLIC_LAT + (lat - old_lat), PUBLIC_LON + (lon - old_lon)
                return updated, True
        if isinstance(value, dict) and {"latitude", "longitude"} <= value.keys():
            lat, lon = value["latitude"], value["longitude"]
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and _distance_m(lat, lon, old_lat, old_lon) <= radius_m:
                updated = dict(value)
                updated["latitude"], updated["longitude"] = PUBLIC_LAT + (lat - old_lat), PUBLIC_LON + (lon - old_lon)
                return updated, True
        if isinstance(value, list) and len(value) == 2 and all(isinstance(item, (int, float)) for item in value):
            lat, lon = value
            if _distance_m(lat, lon, old_lat, old_lon) <= radius_m:
                return [PUBLIC_LAT + (lat - old_lat), PUBLIC_LON + (lon - old_lon)], True
        return value, False

    def recursively(value: Any) -> tuple[Any, bool]:
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                updated = replace_text(value)
                return updated, updated != value
            updated, changed = recursively(decoded)
            return (json.dumps(updated, separators=(",", ":"), ensure_ascii=False), True) if changed else (value, False)
        if isinstance(value, list):
            changed = False
            items = []
            for item in value:
                updated, item_changed = recursively(item)
                items.append(updated)
                changed |= item_changed
            coordinate_updated, coordinate_changed = replace_coordinates(items)
            return coordinate_updated, changed or coordinate_changed
        if isinstance(value, dict):
            changed = False
            items = {}
            for key, item in value.items():
                updated, item_changed = recursively(item)
                items[key] = updated
                changed |= item_changed
            coordinate_updated, coordinate_changed = replace_coordinates(items)
            return coordinate_updated, changed or coordinate_changed
        return value, False

    return recursively


def _protected_projection(db: sqlite3.Connection) -> dict[str, list[tuple[Any, ...]]]:
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    projections: dict[str, list[tuple[Any, ...]]] = {}
    for table, columns in {
        "ledger": "id,budget_id,job_id,reservation_id,payment_id,kind,amount_cents,event_id",
        "jobs": "id,issue_id,plan_id,vendor_id,price_cents,status,state_revision",
        "payments": "id,issue_id,job_id,reservation_id,submission_id,verification_id,amount_cents",
        "invocations": "id,trigger_event_id,trigger_type,signal_id,issue_id,job_id,status,state_revision,fencing_token",
        "issues": "id,status,evidence_score,state_revision,accepted_submission_id,resolved_at",
    }.items():
        if table in tables:
            projections[table] = db.execute(f"SELECT {columns} FROM {table} ORDER BY id").fetchall()
    return projections


def _migrate_copy(destination: sqlite3.Connection, relocate: Any) -> dict[str, int]:
    tables = [row[0] for row in destination.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    trigger_sql = [(row[0], row[1]) for row in destination.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND sql LIKE '%no_update%'"
    ) if row[1]]
    changes: dict[str, int] = {}
    with destination:
        destination.execute("BEGIN IMMEDIATE")
        for name, _sql in trigger_sql:
            destination.execute(f'DROP TRIGGER "{name}"')
        for table in tables:
            columns = [row[1] for row in destination.execute(f'PRAGMA table_info("{table}")') if "TEXT" in row[2].upper()]
            for column in columns:
                rows = destination.execute(f'SELECT rowid, "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL').fetchall()
                count = 0
                for rowid, value in rows:
                    updated, changed = relocate(value)
                    if changed:
                        destination.execute(f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?', (updated, rowid))
                        count += 1
                if count:
                    changes[f"{table}.{column}"] = count
        for _name, sql in trigger_sql:
            destination.execute(sql)
    return changes


def relocate(source: Path, destination: Path, *, issue_id: str, aliases: tuple[str, ...], radius_m: float) -> dict[str, Any]:
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise ValueError("--source and --destination must be different paths")
    if not source.is_file():
        raise ValueError("--source must name an existing SQLite database")
    if destination.exists():
        raise ValueError("--destination must not already exist")
    if radius_m <= 0 or not math.isfinite(radius_m):
        raise ValueError("--coordinate-radius-m must be a positive finite number")

    created_destination = False
    try:
        with closing(_readonly(source)) as source_db:
            if source_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("source integrity check failed")
            _assert_quiescent(source_db)
            legacy_location, old_lat, old_lon = _source_anchor(source_db, issue_id)
            before = _protected_projection(source_db)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise ValueError("--destination must not already exist")
            with closing(sqlite3.connect(destination)) as destination_db:
                created_destination = True
                source_db.backup(destination_db)

        with closing(sqlite3.connect(destination)) as destination_db:
            destination_db.execute("PRAGMA foreign_keys=ON")
            changes = _migrate_copy(destination_db, _relocator(legacy_location, aliases, old_lat, old_lon, radius_m))
            if destination_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("destination integrity check failed")
            if destination_db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("destination foreign-key check failed")
            after = _protected_projection(destination_db)
            if before != after:
                raise ValueError("protected financial, issue, or invocation projection changed")
    except Exception:
        if created_destination:
            destination.unlink(missing_ok=True)
        raise

    return {
        "source": str(source), "destination": str(destination), "issue_id": issue_id,
        "new_location": PUBLIC_LOCATION, "new_coordinates": [PUBLIC_LAT, PUBLIC_LON],
        "coordinate_radius_m": radius_m, "changed_columns": changes,
        "protected_projection": {table: len(rows) for table, rows in before.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Precondition: stop the service and keep the source quiescent for the complete copy.",
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--issue-id", default="demo-couch")
    parser.add_argument("--legacy-alias", action="append", default=[], help="Additional exact legacy text to replace; never stored by this script.")
    parser.add_argument("--coordinate-radius-m", type=float, default=50.0)
    args = parser.parse_args(argv)
    try:
        result = relocate(args.source, args.destination, issue_id=args.issue_id,
                          aliases=tuple(args.legacy_alias), radius_m=args.coordinate_radius_m)
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
