"""Planter, bell profile.

Bell-shaped: narrow at the base, widening to a flared rim at the top. Common
form for decorative brass planters, often hand-chased on the body. Cleanly
sand-castable — the parting line is at the rim and everything tapers
outward as it goes up.
"""

from __future__ import annotations

import cadquery as cq

from mos.templates.base import ParamSpec
from mos.templates.brass._revolve import revolved_shell


class PlanterBell:
    template_id = "planter_bell_v1"
    version = "1.0.0"
    product_family = "planter"
    description = "Bell-profile planter with flared rim."

    param_schema = (
        ParamSpec(
            name="base_diameter",
            description="Outer diameter at the base.",
            min_mm=80.0,
            max_mm=220.0,
        ),
        ParamSpec(
            name="rim_diameter",
            description="Outer diameter at the flared rim.",
            min_mm=120.0,
            max_mm=350.0,
        ),
        ParamSpec(
            name="height",
            description="Overall height base-to-rim.",
            min_mm=80.0,
            max_mm=300.0,
        ),
        ParamSpec(
            name="wall_thickness",
            description="Shell wall thickness.",
            min_mm=3.0,
            max_mm=8.0,
        ),
    )

    regions = ("body", "rim", "base")
    declared_min_wall_mm = 3.0
    declared_min_draft_deg = 2.0
    declared_produces_no_undercuts = True

    def build(self, params: dict[str, float]) -> cq.Workplane:
        base_r = params["base_diameter"] / 2.0
        rim_r = params["rim_diameter"] / 2.0
        height = params["height"]
        wall = params["wall_thickness"]

        # Bell silhouette as a 5-point profile — a smooth approximation
        # rather than true splines, which keeps revolve robust.
        # Mid-height radius is the average plus a small bias, producing a
        # gentle bell curve.
        mid_z = height * 0.55
        mid_r = (base_r + rim_r) / 2.0 - 4.0  # slight inward curve
        upper_z = height * 0.85
        upper_r = (mid_r + rim_r) / 2.0 + 2.0

        outer = [
            (0.0, 0.0),
            (base_r, 0.0),
            (mid_r, mid_z),
            (upper_r, upper_z),
            (rim_r, height),
            (0.0, height),
        ]

        # Cavity: parallel to outer profile, inset by wall. We compute inner
        # radii directly rather than offsetting — that's reliable for these
        # mostly-monotonic profiles.
        cavity_z_start = wall
        cavity_z_end = height - wall

        # Inner radii at each outer waypoint, clamped to >0.
        inner_base_r = max(base_r - wall, 0.1)
        inner_mid_r = max(mid_r - wall, 0.1)
        inner_upper_r = max(upper_r - wall, 0.1)
        inner_rim_r = max(rim_r - wall, 0.1)

        cavity = [
            (0.0, cavity_z_start),
            (inner_base_r, cavity_z_start),
            (inner_mid_r, mid_z),
            (inner_upper_r, upper_z),
            (inner_rim_r, cavity_z_end),
            (0.0, cavity_z_end),
        ]
        return revolved_shell(outer, cavity)
