"""Candle holder, taper-stem profile.

A narrow tapered stem rising from a flared base, topped by a wider cup.
Classic European/Indian crossover form. Sand-castable as one piece — the
stem tapers outward going up to the cup, no undercuts.
"""

from __future__ import annotations

import cadquery as cq

from mos.templates.base import ParamSpec
from mos.templates.brass._revolve import revolved_shell


class CandleHolderTaperStem:
    template_id = "candle_holder_taperstem_v1"
    version = "1.0.0"
    product_family = "candle_holder"
    description = "Tapered-stem candle holder with flared base and cup."

    param_schema = (
        ParamSpec(
            name="base_diameter",
            description="Outer diameter at the flared base.",
            min_mm=70.0,
            max_mm=160.0,
        ),
        ParamSpec(
            name="stem_min_diameter",
            description="Narrowest diameter of the stem (just above base).",
            min_mm=20.0,
            max_mm=50.0,
        ),
        ParamSpec(
            name="cup_diameter",
            description="Outer diameter of the cup at the top.",
            min_mm=35.0,
            max_mm=90.0,
        ),
        ParamSpec(
            name="height",
            description="Overall height base-to-cup-rim.",
            min_mm=100.0,
            max_mm=300.0,
        ),
        ParamSpec(
            name="wall_thickness",
            description="Wall thickness in the cup. Stem is solid below cup.",
            min_mm=3.0,
            max_mm=8.0,
        ),
    )

    regions = ("base", "stem", "cup", "cup_rim")
    declared_min_wall_mm = 3.0
    declared_min_draft_deg = 2.0
    declared_produces_no_undercuts = True

    def build(self, params: dict[str, float]) -> cq.Workplane:
        base_r = params["base_diameter"] / 2.0
        stem_r = params["stem_min_diameter"] / 2.0
        cup_r = params["cup_diameter"] / 2.0
        height = params["height"]
        wall = params["wall_thickness"]

        base_h = min(height * 0.10, 18.0)
        cup_h = min(height * 0.20, 35.0)
        stem_top_z = height - cup_h

        # Outer: base flare → tapered stem → cup widens out.
        outer = [
            (0.0, 0.0),
            (base_r, 0.0),
            (stem_r, base_h),
            (stem_r, stem_top_z),
            (cup_r, stem_top_z + cup_h * 0.3),  # cup flares outward
            (cup_r, height),
            (0.0, height),
        ]

        # Cavity is in the cup only — the stem is solid (it's narrow enough
        # that hollowing it adds risk for minimal weight savings, and matches
        # how brass taper-stems are actually cast).
        cup_floor_z = stem_top_z + cup_h * 0.3 + wall
        cavity_top_z = height - wall
        inner_cup_r = cup_r - wall
        cavity: list[tuple[float, float]] | None = None
        if cavity_top_z > cup_floor_z and inner_cup_r > 0:
            cavity = [
                (0.0, cup_floor_z),
                (inner_cup_r, cup_floor_z),
                (inner_cup_r, cavity_top_z),
                (0.0, cavity_top_z),
            ]
        return revolved_shell(outer, cavity)
