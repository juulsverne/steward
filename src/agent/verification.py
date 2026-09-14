"""Deterministic verification over observable findings, never model confidence."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

PAYMENT_MIN = 95
VERIFICATION_POINTS = {
    "gps_within_30m": 30, "after_later_than_before": 10,
    "target_removed": 40, "no_new_hazard": 10, "area_clear": 10,
}
FINDING_FIELDS = (
    "target_present_before", "same_scene", "target_removed", "no_new_hazard", "area_clear",
)


class VisionFindings(BaseModel):
    """Required nullable booleans; unknown evidence never becomes an affirmative fact."""

    model_config = ConfigDict(strict=True, extra="forbid")
    target_present_before: bool | None = Field(description="Target clearly visible in BEFORE?")
    same_scene: bool | None = Field(description="Same location and comparable viewpoint?")
    target_removed: bool | None = Field(description="Target absent in AFTER?")
    no_new_hazard: bool | None = Field(description=(
        "True when the work introduced no safety hazard (exposed wires, broken glass, spills, fire, "
        "blocked egress). Bags, litter or debris already present that remain are not new hazards; "
        "they only affect area_clear."))
    area_clear: bool | None = Field(description="Work area free of target, bags and loose debris?")
    observations: list[str] = Field(min_length=1, max_length=12, description="Short visible facts")

    @field_validator("observations")
    @classmethod
    def observable_text(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 1000 for item in value):
            raise ValueError("observations must be nonempty, concise visible facts")
        return value


def _boolean(value: bool) -> None:
    if type(value) is not bool:
        raise ValueError("consistency checks must be booleans")


def prerequisites_pass(findings: VisionFindings, *, reuse_detected: bool) -> tuple[bool, list[str]]:
    _boolean(reuse_detected)
    reasons = [name for name in FINDING_FIELDS if getattr(findings, name) is None or (
        name in {"target_present_before", "same_scene"} and getattr(findings, name) is not True
    )]
    if reuse_detected:
        reasons.append("image_reuse")
    return not reasons, reasons


def verification_points(
    findings: VisionFindings, *, gps_within_30m: bool, after_later_than_before: bool,
) -> dict[str, int]:
    """Diagnostic components; callers MUST also apply prerequisites before accepting proof."""
    _boolean(gps_within_30m)
    _boolean(after_later_than_before)
    checks = {
        "gps_within_30m": gps_within_30m, "after_later_than_before": after_later_than_before,
        "target_removed": findings.target_removed, "no_new_hazard": findings.no_new_hazard,
        "area_clear": findings.area_clear,
    }
    return {name: value if checks[name] is True else 0 for name, value in VERIFICATION_POINTS.items()}
