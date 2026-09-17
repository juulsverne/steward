import pytest

from agent.policy import (
    GateResult,
    dispatch_gate,
    distance_m,
    in_district,
    load_policy,
    quote_cents,
    rank_vendors,
    required_equipment,
    route_category,
    settlement_gate,
    vendor_eligibility,
)

POLICY = load_policy("data/policy.yaml")
COUCH = {"lat": 41.88206, "lon": -87.62780}
TRUCK_VENDOR = {
    "id": "south_loop_services", "name": "South Loop Services", "insurance_verified": True,
    "service_categories": ["bulky_waste", "litter"], "service_area": ["south_loop_demo"],
    "equipment": ["truck", "crew_2"], "available": True,
    "distance_km": 1.2, "workload": 2, "performance": 0.94,
}


def test_policy_manifest_carries_the_locked_numbers():
    assert POLICY["version"] == "south-loop-v3"
    assert POLICY["actionable_min_score"] == 70
    assert POLICY["auto_pay_min_score"] == 95
    assert POLICY["max_auto_dispatch_cents"] == 10000
    assert POLICY["budget_cents"] == 50000
    assert POLICY["gps_checkin_max_m"] == 30
    assert POLICY["district_label"].endswith("(seeded)")


def test_missing_policy_keys_are_rejected(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text('{"version": "x"}', encoding="utf-8")
    with pytest.raises(ValueError, match="missing keys"):
        load_policy(path)


@pytest.mark.parametrize("category, hazards, expected", [
    ("bulky_waste", (), "autonomous"),
    ("litter", (), "autonomous"),
    ("pothole", (), "city"),
    ("streetlight", (), "city"),
    ("electrical", (), "never"),
    ("bulky_waste", ("electrical",), "never"),
    ("storefront_damage", (), "review"),
])
def test_route_category_follows_the_policy_lists(category, hazards, expected):
    assert route_category(POLICY, category, hazards) == expected


def test_quote_is_deterministic_and_rejects_unknown_services():
    assert quote_cents(POLICY, "bulky_waste", large_objects=1) == 7200
    assert quote_cents(POLICY, "bulky_waste") == 6000
    assert quote_cents(POLICY, "litter") == 4500
    assert required_equipment(POLICY, "bulky_waste") == ["truck", "crew_2"]
    with pytest.raises(ValueError):
        quote_cents(POLICY, "snow_plowing")
    with pytest.raises(ValueError):
        quote_cents(POLICY, "litter", large_objects=1)
    with pytest.raises(ValueError):
        quote_cents(POLICY, "bulky_waste", large_objects=-1)


def test_geometry_helpers():
    assert distance_m(COUCH["lat"], COUCH["lon"], COUCH["lat"], COUCH["lon"]) == 0
    assert 20 < distance_m(41.88206, -87.62780, 41.88226, -87.62780) < 25
    assert in_district(POLICY, COUCH["lat"], COUCH["lon"])
    assert not in_district(POLICY, 41.90, -87.62)


def test_vendor_eligibility_names_every_reason():
    assert vendor_eligibility(
        POLICY, TRUCK_VENDOR, category="bulky_waste", required_equipment=["truck", "crew_2"]
    ) == []
    van_vendor = {**TRUCK_VENDOR, "id": "lakefront_clean_team", "equipment": ["van", "crew_2"]}
    assert vendor_eligibility(
        POLICY, van_vendor, category="bulky_waste", required_equipment=["truck", "crew_2"]
    ) == ["missing_equipment"]
    bad = {**TRUCK_VENDOR, "insurance_verified": False, "available": False,
           "service_area": ["elsewhere"], "service_categories": ["litter"]}
    assert vendor_eligibility(
        POLICY, bad, category="bulky_waste", required_equipment=["truck"]
    ) == ["insurance_unverified", "category_not_approved", "outside_service_area", "unavailable"]


def test_rank_vendors_prefers_close_light_high_performers():
    near_busy = {**TRUCK_VENDOR, "id": "a", "distance_km": 0.5, "workload": 5}
    far_free = {**TRUCK_VENDOR, "id": "b", "distance_km": 3.0, "workload": 0}
    near_free = {**TRUCK_VENDOR, "id": "c", "distance_km": 0.5, "workload": 0, "performance": 0.8}
    near_free_better = {**TRUCK_VENDOR, "id": "d", "distance_km": 0.5, "workload": 0}
    assert [v["id"] for v in rank_vendors([near_busy, far_free, near_free, near_free_better])] == [
        "d", "c", "a", "b"
    ]


def gate(**overrides):
    base = {
        "issue_status": "ACTIONABLE", "evidence_total": 100, "category": "bulky_waste",
        "hazards": (), "coordinates": COUCH, "vendor": TRUCK_VENDOR,
        "required_equipment": ["truck", "crew_2"], "quote": 7200, "available_cents": 50000,
    }
    return dispatch_gate(POLICY, **{**base, **overrides})


def test_dispatch_gate_allows_the_couch():
    result = gate()
    assert result == GateResult(True, ())
    assert result.reason_code is None
    assert result.to_dict() == {"allowed": True, "reason_code": None, "unmet": []}


@pytest.mark.parametrize("overrides, expected_unmet", [
    ({"issue_status": "MONITORING", "evidence_total": 65},
     ["issue_not_actionable", "evidence_below_threshold"]),
    ({"category": "pothole"}, ["route_city"]),
    ({"hazards": ("electrical",)}, ["route_never"]),
    ({"category": "storefront_damage"}, ["route_review"]),
    ({"coordinates": None}, ["outside_district"]),
    ({"coordinates": {"lat": 41.90, "lon": -87.62}}, ["outside_district"]),
    ({"vendor": {**TRUCK_VENDOR, "equipment": ["van"]}}, ["vendor_missing_equipment"]),
    ({"quote": 10001}, ["quote_over_autonomous_limit"]),
    ({"available_cents": 7199}, ["insufficient_budget"]),
])
def test_dispatch_gate_denies_with_named_requirements(overrides, expected_unmet):
    result = gate(**overrides)
    assert not result.allowed
    assert set(expected_unmet) <= set(result.unmet)
    assert result.reason_code == expected_unmet[0]


def test_settlement_gate_denies_partial_cleanup_and_double_payment():
    ok = settlement_gate(POLICY, job_status="VERIFIED", verification_total=100,
                         prerequisites_passed=True, unmet_checks=[], already_paid=False)
    assert ok.allowed
    partial = settlement_gate(POLICY, job_status="PROOF_SUBMITTED", verification_total=90,
                              prerequisites_passed=True, unmet_checks=["area_clear"],
                              already_paid=False)
    assert list(partial.unmet) == [
        "verification_below_threshold", "check_area_clear", "job_not_verified"
    ]
    reuse = settlement_gate(POLICY, job_status="PROOF_SUBMITTED", verification_total=100,
                            prerequisites_passed=False, unmet_checks=[], already_paid=False)
    assert reuse.reason_code == "prerequisites_failed"
    paid = settlement_gate(POLICY, job_status="PAID", verification_total=100,
                           prerequisites_passed=True, unmet_checks=[], already_paid=True)
    assert paid.reason_code == "already_paid"


@pytest.mark.parametrize("overrides", [
    {"quote": -1}, {"quote": 0}, {"quote": True}, {"quote": 72.0},
    {"available_cents": -1}, {"evidence_total": float("nan")}, {"evidence_total": 101},
])
def test_invalid_numeric_facts_never_authorize_dispatch(overrides):
    with pytest.raises(ValueError):
        gate(**overrides)


def test_truthy_vendor_strings_are_not_approval():
    result = gate(vendor={**TRUCK_VENDOR, "insurance_verified": "false", "available": "yes"})
    assert not result.allowed
    assert "vendor_insurance_unverified" in result.unmet
    assert "vendor_unavailable" in result.unmet


def test_unmet_check_blocks_even_a_supplied_perfect_score():
    result = settlement_gate(POLICY, job_status="VERIFIED", verification_total=100,
                             prerequisites_passed=True, unmet_checks=["image_reuse"],
                             already_paid=False)
    assert not result.allowed
    assert "check_image_reuse" in result.unmet


def test_changed_policy_threshold_is_rejected(tmp_path):
    import json

    path = tmp_path / "policy.yaml"
    path.write_text(json.dumps({**POLICY, "auto_pay_min_score": 90}), encoding="utf-8")
    with pytest.raises(ValueError, match="locked V1"):
        load_policy(path)


@pytest.mark.parametrize("lat,lon", [(float("nan"), 0), (91, 0), (0, 181), (True, 0)])
def test_invalid_geography_is_rejected(lat, lon):
    with pytest.raises(ValueError):
        in_district(POLICY, lat, lon)
