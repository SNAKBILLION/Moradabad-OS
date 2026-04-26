"""Vase, trumpet profile.

Narrow at the base, monotonically widening to a flared rim. No undercuts —
the silhouette is everywhere convex outward as it rises. Cleanly
sand-castable.
"""

from __future__ import annotations

import cadquery as cq

from mos.templates.base import ParamSpec
from mos.templates.brass._revolve import revolved_shell


class VaseTrumpet:
    template_id = "vase_trumpet_v1"
    version = "1.0.0"
    product_family = "vase"
    description = "Trumpet-profile vase: narrow base, flared rim."

    param_schema = (
        ParamSpec(
            name="base_diameter",
            description="Outer diameter at the base.",
            min_mm=40.0,
            max_mm=120.0,
        ),
        ParamSpec(
            name="rim_diameter",
            description="Outer diameter at the rim.",
            min_mm=80.0,
            max_mm=300.0,
        ),
        ParamSpec(
            name="height",
            description="Overall height base-to-rim.",
            min_mm=120.0,
            max_mm=400.0,
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
    declared_min_draft_deg = 2.5  # ample draft from the natural flare
    declared_produces_no_undercuts = True

    def build(self, params: dict[str, float]) -> cq.Workplane:
        base_r = params["base_diameter"] / 2.0
        rim_r = params["rim_diameter"] / 2.0
        height = params["height"]
        wall = params["wall_thickness"]

        # Two intermediate points biased to give the trumpet curve some
        # life rather than a straight cone.
        z1 = height * 0.30
        r1 = base_r + (rim_r - base_r) * 0.15
        z2 = height * 0.70
        r2 = base_r + (rim_r - base_r) * 0.55

        outer = [
            (0.0, 0.0),
            (base_r, 0.0),
            (r1, z1),
            (r2, z2),
            (rim_r, height),
            (0.0, height),
        ]

        cavity_z_start = wall
        cavity_z_end = height - wall
        cavity = [
            (0.0, cavity_z_start),
            (max(base_r - wall, 0.1), cavity_z_start),
            (max(r1 - wall, 0.1), z1),
            (max(r2 - wall, 0.1), z2),
            (max(rim_r - wall, 0.1), cavity_z_end),
            (0.0, cavity_z_end),
        ]
        return revolved_shell(outer, cavity)
