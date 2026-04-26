"""Bowl, spheroid profile.

Hemispherical bowl with a small base flat and a rim band. Cleanly
sand-castable — silhouette monotonically widens from base to rim, parting
line at the rim band.

Implementation: a single closed profile revolved directly into a watertight
bowl shell. We avoid a boolean cut between an outer revolve and a cavity
revolve because OCCT can produce coincident faces at the rim/cavity
boundary that don't tessellate watertightly. The single-profile approach
traces the entire wall outline in one closed polygon:

    (0, 0)
    -> (base_flat_r, 0)              # base outer corner
    -> outer arc up to (rim_r, depth) # outer wall
    -> (rim_r, rim_top_z)             # rim outer corner
    -> (inner_rim_r, rim_top_z)       # rim inner corner
    -> inner arc down to (0, wall)    # inner wall
    -> close back to (0, 0)
"""

from __future__ import annotations

import math

import cadquery as cq

from mos.templates.base import ParamSpec
from mos.templates.brass._revolve import revolve_profile


class BowlSpheroid:
    template_id = "bowl_spheroid_v1"
    version = "1.0.0"
    product_family = "bowl"
    description = "Hemispherical brass bowl with a small base flat."

    param_schema = (
        ParamSpec(
            name="rim_diameter",
            description="Outer diameter at the rim (widest point).",
            min_mm=80.0,
            max_mm=300.0,
        ),
        ParamSpec(
            name="depth",
            description="Internal depth from rim to inner base.",
            min_mm=30.0,
            max_mm=150.0,
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
        rim_r = params["rim_diameter"] / 2.0
        depth = params["depth"]
        wall = params["wall_thickness"]

        rim_band_h = wall
        rim_top_z = depth + rim_band_h
        inner_rim_r = rim_r - wall
        inner_depth = depth - wall

        if inner_rim_r <= 0 or inner_depth <= 0:
            # Degenerate: wall too thick. Fall back to a solid lump.
            n = 16
            outer = [(0.0, 0.0), (max(rim_r * 0.03, 2.0), 0.0)]
            for i in range(1, n + 1):
                theta = (math.pi / 2.0) * (i / n)
                outer.append((rim_r * math.sin(theta),
                              depth - depth * math.cos(theta)))
            outer.append((rim_r, rim_top_z))
            outer.append((0.0, rim_top_z))
            return revolve_profile(outer)

        n = 16
        # Outer arc: (0, 0) -> (rim_r, depth)
        outer_arc: list[tuple[float, float]] = []
        for i in range(n + 1):
            theta = (math.pi / 2.0) * (i / n)
            r = rim_r * math.sin(theta)
            z = depth - depth * math.cos(theta)
            outer_arc.append((r, z))

        # Inner arc: parallel to the outer arc, offset inward. We stop at
        # i=1 (not i=0) so the inner arc never touches the axis — that
        # avoids the degenerate-apex tessellation issue. A short horizontal
        # segment from the last inner-arc point to the centerline closes
        # out the inner floor.
        #
        # The inner arc is the parametric ellipse with semi-axes
        # (inner_rim_r, inner_depth) centered at (0, depth). Walking from
        # rim (i=n) down to i=1 gives r from inner_rim_r toward small but
        # nonzero values, z from depth toward wall+small.
        inner_arc: list[tuple[float, float]] = []
        for i in range(n, 0, -1):  # n down to 1, NOT to 0
            theta = (math.pi / 2.0) * (i / n)
            r = inner_rim_r * math.sin(theta)
            z = wall + (inner_depth - inner_depth * math.cos(theta))
            inner_arc.append((r, z))
        # inner_arc[-1] is at small r (~6mm at i=1, n=16) and z slightly
        # above wall.

        base_flat_r = max(rim_r * 0.03, 2.0)

        profile: list[tuple[float, float]] = [(0.0, 0.0), (base_flat_r, 0.0)]
        profile.extend(outer_arc[1:])             # outer wall up
        profile.append((rim_r, rim_top_z))        # rim outer corner
        profile.append((inner_rim_r, rim_top_z))  # rim inner corner
        profile.append((inner_rim_r, depth))      # down the rim inner edge
        profile.extend(inner_arc[1:])             # inner arc rim->floor (skip dup)
        # last inner_arc point is at small r, z ≈ wall+epsilon. Drop straight
        # to the floor at that small r, then horizontal to the axis.
        last_r, last_z = inner_arc[-1]
        if last_z > wall:
            profile.append((last_r, wall))        # drop to floor at last_r
        profile.append((0.0, wall))               # horizontal to axis
        # close back to (0, 0)

        return revolve_profile(profile)
