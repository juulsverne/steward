"""Deterministic policy: authority, quotes, eligibility, geometry, and mutation gates.

No model involvement. Every function is pure over the policy manifest and stored facts.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_POLICY_PATH = Path("data/policy.yaml")
REQUIRED_KEYS = {
    "version", "district", "district_label", "provenance", "actionable_min_score",
    "precise_geocode_max_m", "image_points", "independent_source_points",
    "independent_source_cap", "precise_geocode_points", "service_match_points",
    "dispute_min_independent_sources", "persistence_points", "persistence_min_hours",
    "autonomous_categories", "route_to_city", "never_dispatch", "max_auto_dispatch_cents",
    "auto_pay_min_score", "gps_checkin_max_m", "rate_cards", "service_area", "budget_cents",
}
LOCKED_NUMBERS = {
    "actionable_min_score": 70, "precise_geocode_max_m": 30, "image_points": 30,
    "independent_source_points": 20, "independent_source_cap": 2,
    "precise_geocode_points": 15, "service_match_points": 15,
    "dispute_min_independent_sources": 2, "persistence_points": 10,
    "persistence_min_hours": 24, "max_auto_dispatch_cents": 10000,
    "auto_pay_min_score": 95, "gps_checkin_max_m": 30,
}


def _integer(value, name: str, minimum: int = 0, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be an integer in the permitted range")


def _coordinates(lat, lon) -> None:
    if (any(type(x) not in (int, float) or not math.isfinite(x) for x in (lat, lon))
            or abs(lat) > 90 or abs(lon) > 180):
        raise ValueError("coordinates must be finite latitude/longitude")


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    unmet: tuple[str, ...] = ()

    @property
    def reason_code(self) -> str | None:
        return self.unmet[0] if self.unmet else None

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason_code": self.reason_code, "unmet": list(self.unmet)}


def load_policy(path: str | Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = REQUIRED_KEYS - set(policy)
    if missing:
        raise ValueError(f"policy manifest missing keys: {sorted(missing)}")
    for name, value in LOCKED_NUMBERS.items():
        if type(policy[name]) is not int or policy[name] != value:
            raise ValueError(f"policy differs from locked V1 rule: {name}")
    if policy["provenance"] != "seeded" or policy["version"] != "south-loop-v3":
        raise ValueError("expected the versioned seeded V1 policy")
    _integer(policy["budget_cents"], "budget_cents")
    area = policy["service_area"]
    _coordinates(area["min_lat"], area["min_lon"])
    _coordinates(area["max_lat"], area["max_lon"])
    if area["min_lat"] >= area["max_lat"] or area["min_lon"] >= area["max_lon"]:
        raise ValueError("service area must have ordered bounds")
    expected_categories = {
        "autonomous_categories": {"litter", "bulky_waste", "approved_graffiti_removal"},
        "route_to_city": {"pothole", "streetlight", "traffic_signal"},
        "never_dispatch": {"electrical", "structural", "hazardous_material"},
    }
    for name, values in expected_categories.items():
        if set(policy[name]) != values:
            raise ValueError(f"policy differs from locked V1 categories: {name}")
    couch = policy["rate_cards"]["bulky_waste"]
    if couch["base_cents"] != 6000 or couch["large_object_cents"] != 1200:
        raise ValueError("bulky waste contract must remain $60 plus $12 per large object")
    for card in policy["rate_cards"].values():
        _integer(card["base_cents"], "base_cents", 1)
        _integer(card.get("large_object_cents", 0), "large_object_cents")
        if not card["required_equipment"]:
            raise ValueError("rate card must state required equipment")
    return policy


def route_category(policy: dict, category: str, hazards=()) -> str:
    never = policy["never_dispatch"]
    if category in never or any(hazard in never for hazard in hazards):
        return "never"
    if category in policy["route_to_city"]:
        return "city"
    if category in policy["autonomous_categories"]:
        return "autonomous"
    return "review"


def _rate_card(policy: dict, service: str) -> dict:
    card = policy["rate_cards"].get(service)
    if card is None:
        raise ValueError(f"no rate card for service {service!r}")
    return card


def quote_cents(policy: dict, service: str, *, large_objects: int = 0) -> int:
    card = _rate_card(policy, service)
    if type(large_objects) is not int or large_objects < 0:
        raise ValueError("large_objects must be a nonnegative integer")
    if large_objects and "large_object_cents" not in card:
        raise ValueError(f"service {service!r} has no large-object rate")
    return card["base_cents"] + large_objects * card.get("large_object_cents", 0)


def required_equipment(policy: dict, service: str) -> list[str]:
    return list(_rate_card(policy, service)["required_equipment"])


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    _coordinates(lat1, lon1)
    _coordinates(lat2, lon2)
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1, max(0, a))))


def in_district(policy: dict, lat: float, lon: float) -> bool:
    _coordinates(lat, lon)
    area = policy["service_area"]
    return area["min_lat"] <= lat <= area["max_lat"] and area["min_lon"] <= lon <= area["max_lon"]


def vendor_eligibility(policy: dict, vendor: dict, *, category: str,
                       required_equipment: list[str]) -> list[str]:
    """Reasons a vendor is ineligible, in a fixed order. Empty means eligible."""
    reasons: list[str] = []
    if vendor.get("insurance_verified") is not True:
        reasons.append("insurance_unverified")
    if category not in vendor.get("service_categories", []):
        reasons.append("category_not_approved")
    if policy["district"] not in vendor.get("service_area", []):
        reasons.append("outside_service_area")
    if not set(required_equipment) <= set(vendor.get("equipment", [])):
        reasons.append("missing_equipment")
    if vendor.get("available") is not True:
        reasons.append("unavailable")
    return reasons


def rank_vendors(vendors: list[dict]) -> list[dict]:
    """Closest first, then lightest workload, then best performance, then stable id order."""
    return sorted(
        vendors,
        key=lambda v: (v["distance_km"], v["workload"], -v["performance"], v["id"]),
    )


def dispatch_gate(policy: dict, *, issue_status: str, evidence_total: int, category: str,
                  hazards, coordinates: dict | None, vendor: dict, required_equipment: list[str],
                  quote: int, available_cents: int) -> GateResult:
    """Pure predicate over stored facts; the mutation owner must recompute the contract quote."""
    _integer(evidence_total, "evidence_total", maximum=100)
    _integer(quote, "quote", 1)
    _integer(available_cents, "available_cents")
    unmet: list[str] = []
    if issue_status != "ACTIONABLE":
        unmet.append("issue_not_actionable")
    if evidence_total < policy["actionable_min_score"]:
        unmet.append("evidence_below_threshold")
    route = route_category(policy, category, hazards)
    if route != "autonomous":
        unmet.append(f"route_{route}")
    if coordinates is None or not in_district(policy, coordinates["lat"], coordinates["lon"]):
        unmet.append("outside_district")
    unmet.extend(
        f"vendor_{reason}" for reason in vendor_eligibility(
            policy, vendor, category=category, required_equipment=required_equipment
        )
    )
    if quote > policy["max_auto_dispatch_cents"]:
        unmet.append("quote_over_autonomous_limit")
    if quote > available_cents:
        unmet.append("insufficient_budget")
    return GateResult(not unmet, tuple(unmet))


def settlement_gate(policy: dict, *, job_status: str, verification_total: int,
                    prerequisites_passed: bool, unmet_checks: list[str],
                    already_paid: bool) -> GateResult:
    _integer(verification_total, "verification_total", maximum=100)
    if type(prerequisites_passed) is not bool or type(already_paid) is not bool:
        raise ValueError("settlement facts must be booleans")
    unmet: list[str] = []
    if already_paid:
        unmet.append("already_paid")
    if not prerequisites_passed:
        unmet.append("prerequisites_failed")
    if verification_total < policy["auto_pay_min_score"]:
        unmet.append("verification_below_threshold")
    unmet.extend(f"check_{check}" for check in unmet_checks)
    if job_status != "VERIFIED":
        unmet.append("job_not_verified")
    return GateResult(not unmet, tuple(unmet))
