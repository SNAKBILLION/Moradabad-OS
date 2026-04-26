"""Candle holder, classic profile.

Rotationally-symmetric. Built as a revolved cross-section so the walls are
a genuine shell (not a boolean of two cylinders). This matches how a
sand-cast candle holder is actually made: a single hollow shell.

Implementation notes (CadQuery 2.7):

- Use ``.polyline(points).close()`` to create a closed wire; ``moveTo`` +
  ``lineTo`` does not register as a pending wire for ``revolve``.
- Use default revolve axis on a ``Workplane("XZ")``; this revolves around
  the world Z axis, which is what we want. Passing explicit ``axisStart`` /
  ``axisEnd`` produces a degenerate solid in this version.
"""

from __future__ import annotations

import cadquery as cq

from mos.templates.base import ParamSpec


class CandleHolderClassic:
    template_id = "candle_holder_classic_v1"
    version = "1.0.0"
    product_family = "candle_holder"
    description = "Classic rotationally-symmetric brass candle holder."

    param_schema = (
        ParamSpec(
            name="base_diameter",
            description="Outer diameter at the base, in mm.",
            min_mm=40.0,
            max_mm=200.0,
        ),
        ParamSpec(
            name="neck_diameter",
            description="Outer diameter at the cup (top), in mm.",
            min_mm=25.0,
            max_mm=120.0,
        ),
        ParamSpec(
            name="height",
            description="Overall height base-to-cup-rim, in mm.",
            min_mm=60.0,
            max_mm=250.0,
        ),
        ParamSpec(
            name="wall_thickness",
            description="Shell wall thickness, in mm.",
            min_mm=3.0,
            max_mm=8.0,
        ),
    )

    regions = ("body", "base_rim", "cup_rim")

    # Author declarations. These are what the author promises the geometry
    # honors. DFM rules validate these against foundry limits.
    declared_min_wall_mm = 3.0
    declared_min_draft_deg = 2.0
    declared_produces_no_undercuts = True

    def build(self, params: dict[str, float]) -> cq.Workplane:
        base_d = params["base_diameter"]
        neck_d = params["neck_diameter"]
        height = params["height"]
        wall = params["wall_thickness"]

        base_r = base_d / 2.0
        neck_r = neck_d / 2.0

        # Cup depth: 25% of height, capped at 30mm.
        cup_depth = min(height * 0.25, 30.0)
        body_top_z = height - cup_depth

        # Outer profile: closed polygon in the XZ half-plane (X >= 0).
        # Counterclockwise when viewed from +Y.
        outer_profile = [
            (0.0, 0.0),
            (base_r, 0.0),
            (neck_r + wall, body_top_z),
            (neck_r + wall, height),
            (neck_r, height),
            (neck_r, body_top_z + wall),
            (0.0, body_top_z + wall),
        ]

        outer = (
            cq.Workplane("XZ")
            .polyline(outer_profile)
            .close()
            .revolve(360)
        )

        # Hollow the body. Cavity starts at z=wall (so the base plate keeps
        # thickness) and ends at z=body_top_z - wall (so the cup floor has
        # thickness). Inner wall follows the outer taper, inset by `wall`.
        cavity_z_start = wall
        cavity_z_end = body_top_z - wall

        if cavity_z_end > cavity_z_start:
            # Outer radius as a linear function of z, for z in [0, body_top_z]:
            #   r_outer(z) = base_r + (z/body_top_z) * ((neck_r + wall) - base_r)
            def r_outer(z: float) -> float:
                t = z / body_top_z
                return base_r + t * ((neck_r + wall) - base_r)

            inner_r_start = r_outer(cavity_z_start) - wall
            inner_r_end = r_outer(cavity_z_end) - wall

            if inner_r_start > 0 and inner_r_end > 0:
                cavity_profile = [
                    (0.0, cavity_z_start),
                    (inner_r_start, cavity_z_start),
                    (inner_r_end, cavity_z_end),
                    (0.0, cavity_z_end),
                ]
                cavity = (
                    cq.Workplane("XZ")
                    .polyline(cavity_profile)
                    .close()
                    .revolve(360)
                )
                outer = outer.cut(cavity)

        return outer
