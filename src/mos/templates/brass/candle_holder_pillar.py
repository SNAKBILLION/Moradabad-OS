"""Candle holder, pillar profile.

Straight cylindrical body with a flared base. Common Moradabad export form.
No undercuts — cleanly sand-castable as a single piece with a horizontal
parting line at the base flare.
"""

from __future__ import annotations

import cadquery as cq

from mos.templates.base import ParamSpec
from mos.templates.brass._revolve import revolved_shell


class CandleHolderPillar:
    template_id = "candle_holder_pillar_v1"
    version = "1.0.0"
    product_family = "candle_holder"
    description = "Straight pillar candle holder with flared base."

    param_schema = (
        ParamSpec(
            name="body_diameter",
            description="Outer diameter of the cylindrical body.",
            min_mm=40.0,
            max_mm=120.0,
        ),
        ParamSpec(
            name="base_diameter",
            description="Outer diameter at the flared base.",
            min_mm=60.0,
            max_mm=180.0,
        ),
        ParamSpec(
            name="base_height",
            description="Height of the flared base section.",
            min_mm=8.0,
            max_mm=30.0,
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

    regions = ("body", "base", "rim")
    declared_min_wall_mm = 3.0
    declared_min_draft_deg = 2.0
    declared_produces_no_undercuts = True

    def build(self, params: dict[str, float]) -> cq.Workplane:
        body_r = params["body_diameter"] / 2.0
        base_r = params["base_diameter"] / 2.0
        base_h = params["base_height"]
        height = params["height"]
        wall = params["wall_thickness"]

        # Outer: flared base (cone frustum) into a cylinder.
        outer = [
            (0.0, 0.0),
            (base_r, 0.0),
            (body_r, base_h),
            (body_r, height),
            (0.0, height),
        ]

        # Cavity: starts above the base interior thickness, ends below the
        # rim by `wall`. Inner radius is body_r - wall everywhere except
        # within the base flare, where it follows the cone (with offset).
        cavity_start_z = wall
        cavity_end_z = height - wall
        cavity: list[tuple[float, float]] | None = None
        if cavity_end_z > cavity_start_z:
            # Inner radius at z=cavity_start_z follows the outer cone if
            # the cavity starts inside the flare; otherwise it's body_r-wall.
            if cavity_start_z < base_h:
                t = cavity_start_z / base_h if base_h > 0 else 1.0
                inner_r_at_start = (base_r + t * (body_r - base_r)) - wall
            else:
                inner_r_at_start = body_r - wall
            inner_r_top = body_r - wall

            if inner_r_at_start > 0 and inner_r_top > 0:
                cavity = [
                    (0.0, cavity_start_z),
                    (inner_r_at_start, cavity_start_z),
                    (inner_r_top, base_h) if cavity_start_z < base_h else
                    (inner_r_top, cavity_start_z + 0.001),
                    (inner_r_top, cavity_end_z),
                    (0.0, cavity_end_z),
                ]

        return revolved_shell(outer, cavity)
