"""Planter, cylinder profile.

Straight-sided cylindrical planter. Simplest form — cleanly sand-castable
with a parting line at the rim.
"""

from __future__ import annotations

import cadquery as cq

from mos.templates.base import ParamSpec
from mos.templates.brass._revolve import revolved_shell


class PlanterCylinder:
    template_id = "planter_cylinder_v1"
    version = "1.0.0"
    product_family = "planter"
    description = "Straight-sided cylindrical planter."

    param_schema = (
        ParamSpec(
            name="diameter",
            description="Outer diameter (constant top to bottom).",
            min_mm=80.0,
            max_mm=300.0,
        ),
        ParamSpec(
            name="height",
            description="Overall height.",
            min_mm=60.0,
            max_mm=350.0,
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
    # Pure cylinders have no draft; for sand casting this is borderline.
    # Decoupled from the foundry's recommended minimum on purpose — the
    # DFM check produces a WARN here, factory partner accepts or routes to
    # a slightly tapered variant.
    declared_min_draft_deg = 0.5
    declared_produces_no_undercuts = True

    def build(self, params: dict[str, float]) -> cq.Workplane:
        r = params["diameter"] / 2.0
        height = params["height"]
        wall = params["wall_thickness"]

        outer = [
            (0.0, 0.0),
            (r, 0.0),
            (r, height),
            (0.0, height),
        ]

        cavity_z_start = wall
        cavity_z_end = height - wall
        inner_r = r - wall
        cavity: list[tuple[float, float]] | None = None
        if cavity_z_end > cavity_z_start and inner_r > 0:
            cavity = [
                (0.0, cavity_z_start),
                (inner_r, cavity_z_start),
                (inner_r, cavity_z_end),
                (0.0, cavity_z_end),
            ]
        return revolved_shell(outer, cavity)
