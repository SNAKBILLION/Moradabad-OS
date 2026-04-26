"""Bowl, footed profile.

A hemispherical bowl on a stepped foot. Cleanly sand-castable — the foot
is below where the bowl widens, so the silhouette is monotonically widening
above the foot's flare. Parting line at the rim band.

Implementation: single closed profile revolved directly into a watertight
shell. Same pattern as bowl_spheroid_v1 — see that module for the rationale
behind the inner-arc-stops-short-of-axis approach.
"""

from __future__ import annotations

import math

import cadquery as cq

from mos.templates.base import ParamSpec
from mos.templates.brass._revolve import revolve_profile


class BowlFooted:
    template_id = "bowl_footed_v1"
    version = "1.0.0"
    product_family = "bowl"
    description = "Hemispherical bowl on a stepped foot."

    param_schema = (
        ParamSpec(
            name="rim_diameter",
            description="Outer diameter at the rim.",
            min_mm=100.0,
            max_mm=300.0,
        ),
        ParamSpec(
            name="depth",
            description="Bowl-only depth (rim to inner base of the bowl).",
            min_mm=30.0,
            max_mm=140.0,
        ),
        ParamSpec(
            name="foot_diameter",
            description="Outer diameter of the foot.",
            min_mm=50.0,
            max_mm=180.0,
        ),
        ParamSpec(
            name="foot_height",
            description="Height of the foot section.",
            min_mm=10.0,
            max_mm=40.0,
        ),
        ParamSpec(
            name="wall_thickness",
            description="Bowl wall thickness.",
            min_mm=3.0,
            max_mm=8.0,
        ),
    )

    regions = ("body", "foot", "rim", "base")
    declared_min_wall_mm = 3.0
    declared_min_draft_deg = 2.0
    declared_produces_no_undercuts = True

    def build(self, params: dict[str, float]) -> cq.Workplane:
        rim_r = params["rim_diameter"] / 2.0
        depth = params["depth"]
        foot_r = params["foot_diameter"] / 2.0
        foot_h = params["foot_height"]
        wall = params["wall_thickness"]

        rim_band_h = wall
        bowl_top_z = foot_h + depth
        rim_top_z = bowl_top_z + rim_band_h
        inner_rim_r = rim_r - wall
        inner_depth = depth - wall

        if inner_rim_r <= 0 or inner_depth <= 0:
            # Wall too thick — fall back to solid body to avoid crashing.
            n = 12
            outer = [(0.0, 0.0), (foot_r, 0.0), (foot_r, foot_h)]
            for i in range(1, n + 1):
                theta = (math.pi / 2.0) * (i / n)
                outer.append((
                    foot_r + (rim_r - foot_r) * math.sin(theta),
                    foot_h + depth * (1 - math.cos(theta)),
                ))
            outer.append((rim_r, rim_top_z))
            outer.append((0.0, rim_top_z))
            return revolve_profile(outer)

        n = 12
        # Outer arc: foot top (foot_r, foot_h) -> rim (rim_r, bowl_top_z).
        outer_arc: list[tuple[float, float]] = []
        for i in range(n + 1):
            theta = (math.pi / 2.0) * (i / n)
            r = foot_r + (rim_r - foot_r) * math.sin(theta)
            z = foot_h + depth * (1 - math.cos(theta))
            outer_arc.append((r, z))

        # Inner arc: parallel to the outer arc, offset inward by `wall`.
        # Outer arc has center (foot_r, foot_h+depth), semi-axes
        # (rim_r-foot_r, depth). For a uniform-thickness shell the inner
        # arc has the same center, semi-axes shrunk by `wall`:
        #   center = (foot_r, foot_h + depth)
        #   semi-x = (rim_r - foot_r) - wall
        #   semi-y = depth - wall
        # We walk rim-end first; stop at i=1 to avoid an axis-degenerate
        # apex (see bowl_spheroid for the rationale).
        inner_cx = foot_r
        inner_cy = foot_h + depth
        inner_sx = (rim_r - foot_r) - wall
        inner_sy = depth - wall
        if inner_sx <= 0 or inner_sy <= 0:
            # Wall too thick for the rim-foot delta — fall back.
            n_fb = 12
            outer = [(0.0, 0.0), (foot_r, 0.0), (foot_r, foot_h)]
            for i in range(1, n_fb + 1):
                theta = (math.pi / 2.0) * (i / n_fb)
                outer.append((
                    foot_r + (rim_r - foot_r) * math.sin(theta),
                    foot_h + depth * (1 - math.cos(theta)),
                ))
            outer.append((rim_r, rim_top_z))
            outer.append((0.0, rim_top_z))
            return revolve_profile(outer)

        inner_arc: list[tuple[float, float]] = []
        for i in range(n, 0, -1):
            theta = (math.pi / 2.0) * (i / n)
            r = inner_cx + inner_sx * math.sin(theta)
            z = inner_cy - inner_sy * math.cos(theta)
            inner_arc.append((r, z))

        # Single closed profile: foot up, outer arc up to rim, rim band,
        # rim inner corner, drop, inner arc down, horizontal to axis, close.
        profile: list[tuple[float, float]] = [
            (0.0, 0.0),
            (foot_r, 0.0),
            (foot_r, foot_h),
        ]
        profile.extend(outer_arc[1:])             # outer arc to rim
        profile.append((rim_r, rim_top_z))        # rim outer corner
        profile.append((inner_rim_r, rim_top_z))  # rim inner corner
        profile.append((inner_rim_r, bowl_top_z))  # down rim inner edge
        profile.extend(inner_arc[1:])             # inner arc descending
        # The last inner-arc point is at small r and z close to the
        # bowl-floor z (= inner_cy - inner_sy = foot_h + depth - inner_sy
        # = foot_h + wall). Drop straight down (if needed) and close to the
        # axis at the inner-floor z.
        last_r, last_z = inner_arc[-1]
        floor_z = inner_cy - inner_sy  # foot_h + wall
        if last_z > floor_z:
            profile.append((last_r, floor_z))     # drop to floor
        profile.append((0.0, floor_z))            # horizontal to axis
        # close back to (0, 0)

        return revolve_profile(profile)
