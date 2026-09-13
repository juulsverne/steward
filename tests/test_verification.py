import pytest

from agent.verification import VisionFindings, prerequisites_pass, verification_points


def findings(**changes):
    return VisionFindings(**{
        "target_present_before": True, "same_scene": True, "target_removed": True,
        "no_new_hazard": True, "area_clear": True, "observations": ["Couch gone."],
        **changes,
    })


def test_partial_and_complete_cleanup_scores():
    for clear, total in [(False, 90), (True, 100)]:
        points = verification_points(
            findings(area_clear=clear), gps_within_30m=True, after_later_than_before=True
        )
        assert sum(points.values()) == total
        assert points["area_clear"] == (10 if clear else 0)


@pytest.mark.parametrize("field", [
    "target_present_before", "same_scene", "target_removed", "no_new_hazard", "area_clear",
])
def test_every_unknown_finding_blocks_acceptance(field):
    ok, reasons = prerequisites_pass(findings(**{field: None}), reuse_detected=False)
    assert not ok
    assert field in reasons


@pytest.mark.parametrize("field", ["target_present_before", "same_scene"])
def test_absent_target_or_wrong_scene_cannot_pass_a_perfect_score(field):
    result = findings(**{field: False})
    assert sum(verification_points(
        result, gps_within_30m=True, after_later_than_before=True
    ).values()) == 100
    assert prerequisites_pass(result, reuse_detected=False) == (False, [field])


def test_reuse_blocks_and_bad_consistency_checks_lose_points():
    assert prerequisites_pass(findings(), reuse_detected=True) == (False, ["image_reuse"])
    assert prerequisites_pass(findings(), reuse_detected=False) == (True, [])
    assert sum(verification_points(
        findings(), gps_within_30m=False, after_later_than_before=False
    ).values()) == 60


@pytest.mark.parametrize("changes", [
    {"target_removed": "yes"}, {"same_scene": 1}, {"observations": []},
    {"observations": [" "]}, {"payable": True},
])
def test_malformed_findings_are_rejected(changes):
    with pytest.raises(ValueError):
        findings(**changes)


def test_consistency_inputs_cannot_use_truthy_values():
    with pytest.raises(ValueError):
        verification_points(findings(), gps_within_30m="false", after_later_than_before=True)
    with pytest.raises(ValueError):
        prerequisites_pass(findings(), reuse_detected="false")
