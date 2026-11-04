"""Legal axle-load and gross-mass limits used by the clearance engine.

IMPORTANT — LEGAL VERIFICATION REQUIRED. The figures below reflect the East African Community Vehicle Load Control Act,
2016 (as applied in Kenya and enforced by KeNHA) *as understood by the engineering team*. They are configuration, not
code: the `limits_version` string is stored with every decision so that a change in the schedule never silently changes
the meaning of historical decisions. Before any pilot, the values must be confirmed against the current schedule and the
regulator's tolerance policy and this file updated with a new version string.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LimitSet:
    version: str
    steering_single_kg: int = 8_000  # first axle (group of 1, steering)
    single_drive_kg: int = 10_000  # any other single axle (dual tyres)
    tandem_kg: int = 18_000  # group of 2
    tridem_kg: int = 24_000  # group of 3
    quad_kg: int = 24_000  # groups of 4+ are not expected; treated as tridem limit (conservative)
    gvm_max_kg: int = 56_000
    # Enforcement tolerance applied to axle-group limits (percentage). The EAC Act provides a tolerance on axle load;
    # the exact value and whether it applies to GVM must be confirmed with the regulator. Default: 5 % on axle groups, 0 % on GVM.
    axle_tolerance_pct: float = 5.0
    gvm_tolerance_pct: float = 0.0
    # Conservative margin: in addition to measurement uncertainty, require this margin before GREEN (kg).
    green_safety_margin_kg: int = 250
    notes: list[str] = field(
        default_factory=lambda: [
            "Values to be verified against EAC Vehicle Load Control Act 2016 schedule before pilot.",
            "Tolerance policy to be confirmed with KeNHA.",
        ]
    )

    def group_limit_kg(self, group_index: int, group_size: int) -> int:
        if group_size == 1:
            return self.steering_single_kg if group_index == 0 else self.single_drive_kg
        if group_size == 2:
            return self.tandem_kg
        if group_size == 3:
            return self.tridem_kg
        return self.quad_kg

    def gvm_limit_for_config(self, group_sizes: list[int]) -> int:
        if not group_sizes:
            return self.gvm_max_kg
        s = sum(self.group_limit_kg(i, g) for i, g in enumerate(group_sizes))
        return min(s, self.gvm_max_kg)


DEFAULT_LIMITS = LimitSet(version="KE-EAC-VLC-2016-schedule-v1")


def parse_axle_config(cfg: str) -> list[int]:
    try:
        return [int(x) for x in cfg.replace(" ", "").split("+") if x]
    except ValueError:
        return []
