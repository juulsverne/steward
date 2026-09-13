import json
from pathlib import Path

import pytest

from agent.vision_spike import PRIOR_COMPLETIONS, consistency, evaluate_run, run_spike, spike_passed


def findings(**changes):
    return {
        "target_present_before": True, "same_scene": True, "target_removed": True,
        "no_new_hazard": True, "area_clear": True, "observations": ["Visible evidence."],
        **changes,
    }


def run(role, **changes):
    return evaluate_run(role, findings(**changes), reuse_detected=role == "reused",
                        gps_within_30m=True, after_later_than_before=True)


def test_spike_requires_all_expected_outcomes_in_every_repeat():
    pairings = {
        "middle": [run("middle", area_clear=False)] * 3,
        "after": [run("after")] * 3,
        "unrelated": [run("unrelated", same_scene=False)] * 3,
        "reused": [run("reused")] * 3,
    }
    assert spike_passed(pairings, repeats=3)
    assert not spike_passed({role: runs[:1] for role, runs in pairings.items()}, repeats=1)
    pairings["after"] = [run("after", area_clear=None)] * 3
    assert not spike_passed(pairings, repeats=3)
    pairings["after"] = [{"error": "ExpiredTokenException"}] * 3
    assert not spike_passed(pairings, repeats=3)
    assert not spike_passed({}, repeats=3)
    with pytest.raises(ValueError):
        spike_passed({}, repeats=0)


def test_false_acceptance_and_incorrect_partial_score_fail_the_gate():
    assert run("middle")["false_automatic_acceptance"]
    assert not run("middle")["matches_expectation"]
    assert not run("middle", area_clear=False, target_removed=False)["matches_expectation"]


def test_rework_reuse_includes_the_failed_prior_completion():
    assert PRIOR_COMPLETIONS["after"] == ["middle"]
    assert set(PRIOR_COMPLETIONS["reused"]) == {"middle", "after"}
    assert all("before" not in roles for roles in PRIOR_COMPLETIONS.values())


def test_spike_errors_remain_failures_with_checkpoints(tmp_path):
    saved = []

    def unavailable(*args, **kwargs):
        raise RuntimeError("not model evidence")

    result = run_spike(Path("data/images"), repeats=1, interval_s=0, inspector=unavailable,
                       checkpoint=lambda value: saved.append(json.dumps(value)))
    assert result["mode"] == "test"
    assert not result["passed"]
    assert len(saved) == 5
    assert all(runs[0]["error"] == "RuntimeError" for runs in result["pairings"].values())
    assert result["pairings"]["reused"][0]["reuse_detected"]
    assert not result["pairings"]["after"][0]["reuse_detected"]


def test_consistency_uses_observation_time_and_distance():
    metadata = json.loads(Path("data/images/consistency.json").read_text())
    checks = consistency(metadata, "after")
    assert 8 < checks["gps_distance_m"] < 10
    assert checks["after_later_than_before"]
    metadata["observed_at"]["after"] = metadata["observed_at"]["before"]
    metadata["checkin_location"] = [42, -87]
    checks = consistency(metadata, "after")
    assert not checks["gps_within_30m"]
    assert not checks["after_later_than_before"]


def test_modified_asset_blocks_inference_before_it_runs(tmp_path):
    import shutil

    for path in Path("data/images").iterdir():
        shutil.copyfile(path, tmp_path / path.name)
    (tmp_path / "after.jpg").write_bytes((tmp_path / "middle.jpg").read_bytes())
    with pytest.raises(ValueError, match="frozen manifest"):
        run_spike(tmp_path, repeats=1, interval_s=0, inspector=lambda *a, **k: pytest.fail())
