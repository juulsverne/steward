"""Four real image comparisons, repeated three times; strict gate, retained failures."""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

from .config import settings
from .images import dhash, hamming, looks_reused, sha256_of
from .models import utc_time
from .verification import PAYMENT_MIN, VisionFindings, prerequisites_pass, verification_points
from .vision import PROMPT_VERSION, SYSTEM_PROMPT, inspect_pair_result

TARGET = "the brown fabric couch"
WORK_AREA = "the foreground sidewalk occupied by the couch, black trash bags, and loose paper litter"
PAIRINGS = {
    "middle": {"prerequisites": True, "payable": False, "total": 90,
               "fields": {"target_removed": True, "no_new_hazard": True, "area_clear": False}},
    "after": {"prerequisites": True, "payable": True, "total": 100,
              "fields": {"target_removed": True, "no_new_hazard": True, "area_clear": True}},
    "unrelated": {"prerequisites": False, "payable": False, "fields": {"same_scene": False}},
    "reused": {"prerequisites": False, "payable": False, "fields": {}},
}
PRIOR_COMPLETIONS = {"middle": [], "after": ["middle"], "unrelated": [],
                     "reused": ["middle", "after"]}


def evaluate_run(role: str, raw_findings: dict, *, reuse_detected: bool,
                 gps_within_30m: bool, after_later_than_before: bool) -> dict:
    findings = VisionFindings.model_validate(raw_findings)
    ok, reasons = prerequisites_pass(findings, reuse_detected=reuse_detected)
    points = verification_points(findings, gps_within_30m=gps_within_30m,
                                 after_later_than_before=after_later_than_before)
    total = sum(points.values())
    payable = ok and total >= PAYMENT_MIN
    expected = PAIRINGS[role]
    fields_match = all(raw_findings[key] == value for key, value in expected["fields"].items())
    return {
        "findings": findings.model_dump(), "reuse_detected": reuse_detected,
        "prerequisites_pass": ok, "failed_prerequisites": reasons, "points": points,
        "total": total, "automatic_payment": payable,
        "false_automatic_acceptance": payable and not expected["payable"],
        "matches_expected_fields": fields_match,
        "matches_expectation": fields_match and ok == expected["prerequisites"]
        and payable == expected["payable"] and total == expected.get("total", total)
        and (role != "reused" or reuse_detected),
    }


def spike_passed(pairings: dict, *, repeats: int) -> bool:
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    return repeats >= 3 and set(pairings) == set(PAIRINGS) and all(
        len(runs) == repeats and all(
            not run.get("error") and run.get("matches_expectation") is True for run in runs
        ) for runs in pairings.values()
    )


def consistency(metadata: dict, role: str) -> dict:
    def coordinates(value):
        lat, lon = value
        if (any(type(x) not in (int, float) or not math.isfinite(x) for x in value)
                or abs(lat) > 90 or abs(lon) > 180):
            raise ValueError("invalid seeded coordinates")
        return math.radians(lat), math.radians(lon)

    lat1, lon1 = coordinates(metadata["job_location"])
    lat2, lon2 = coordinates(metadata["checkin_location"])
    term = math.sin((lat2 - lat1) / 2) ** 2
    term += math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    distance = 6_371_000 * 2 * math.asin(math.sqrt(min(1, term)))
    before = utc_time(metadata["observed_at"]["before"])
    after = utc_time(metadata["observed_at"][role])
    return {
        "provenance": "seeded", "gps_distance_m": distance, "gps_within_30m": distance <= 30,
        "before_observed_at": before.isoformat(), "after_observed_at": after.isoformat(),
        "after_later_than_before": after > before,
    }


def run_spike(images: Path, *, repeats: int = 3, interval_s: float = 7,
              inspector=None, checkpoint=None) -> dict:
    spike_passed({}, repeats=repeats)
    if not math.isfinite(interval_s) or interval_s < 0:
        raise ValueError("interval must be finite and nonnegative")
    metadata = json.loads((images / "consistency.json").read_text(encoding="utf-8"))
    if metadata.get("provenance") != "seeded":
        raise ValueError("spike consistency metadata must be explicitly seeded")
    manifest = json.loads((images / "manifest.json").read_text(encoding="utf-8"))
    hashes = {}
    for role in ("before", *PAIRINGS):
        path = images / f"{role}.jpg"
        hashes[role] = {"sha256": sha256_of(path), "dhash": dhash(path)}
        if any(hashes[role][key] != manifest["images"][role][key] for key in hashes[role]):
            raise ValueError(f"image differs from frozen manifest: {role}")
    results = {
        "ran_at": datetime.now(UTC).isoformat(), "mode": "live" if inspector is None else "test",
        "model_id": settings.resolved_vision_model_id,
        "vision_model_id": settings.resolved_vision_model_id,
        "region": settings.region, "repeats": repeats,
        "temperature": 0, "max_tokens": 1024, "system_prompt": SYSTEM_PROMPT,
        "prompt_version": PROMPT_VERSION, "target": TARGET, "work_area": WORK_AREA,
        "images": hashes, "consistency_inputs": metadata, "pairings": {}, "passed": False,
    }
    inspect = inspector or inspect_pair_result
    last_started = None
    for role in PAIRINGS:
        runs = results["pairings"][role] = []
        checks = consistency(metadata, role)
        prior = PRIOR_COMPLETIONS[role]
        distances = {name: hamming(hashes[role]["dhash"], hashes[name]["dhash"]) for name in prior}
        reuse = looks_reused(hashes[role]["dhash"], [hashes[name]["dhash"] for name in prior])
        for attempt in range(1, repeats + 1):
            if last_started is not None:
                time.sleep(max(0, interval_s - (time.perf_counter() - last_started)))
            last_started = time.perf_counter()
            run = {"attempt": attempt, "consistency": checks, "prior_completions": prior,
                   "prior_dhash_distances": distances, "reuse_detected": reuse}
            try:
                inspection = inspect((images / "before.jpg").read_bytes(),
                                     (images / f"{role}.jpg").read_bytes(),
                                     target=TARGET, work_area=WORK_AREA)
                run["inspection"] = inspection
                run.update(evaluate_run(
                    role, inspection["findings"], reuse_detected=reuse,
                    gps_within_30m=checks["gps_within_30m"],
                    after_later_than_before=checks["after_later_than_before"],
                ))
            except Exception as exc:  # noqa: BLE001 - each failed inspection remains in the artifact
                run["error"] = type(exc).__name__
                if hasattr(exc, "inspection"):
                    run["inspection"] = exc.inspection
            run["latency_s"] = round(time.perf_counter() - last_started, 3)
            runs.append(run)
            if checkpoint:
                checkpoint(results)
    results["passed"] = spike_passed(results["pairings"], repeats=repeats)
    if checkpoint:
        checkpoint(results)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, default=Path("data/images"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--interval", type=float, default=7)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.repeats < 1 or not math.isfinite(args.interval) or args.interval < 0:
        parser.error("repeats must be positive and interval finite/nonnegative")
    out = args.out or Path(".steward") / f"vision-spike-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x+", encoding="utf-8") as file:
        def checkpoint(results):
            file.seek(0)
            json.dump(results, file, indent=2)
            file.write("\n")
            file.truncate()
            file.flush()
            print(f"Recorded {sum(map(len, results['pairings'].values()))} inspections", flush=True)

        results = run_spike(args.images, repeats=args.repeats,
                            interval_s=args.interval, checkpoint=checkpoint)
    for role, runs in results["pairings"].items():
        passed = sum(run.get("matches_expectation") is True for run in runs)
        print(f"{role}: {passed}/{len(runs)} expected outcomes")
    print(f"{'PASS' if results['passed'] else 'FAIL'} — {out.resolve()}")
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
