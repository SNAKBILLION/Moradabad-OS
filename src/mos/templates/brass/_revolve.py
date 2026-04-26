"""Helpers shared across rotationally-symmetric brass templates.

Every Phase-1 archetype is a revolved shell: a 2D outer profile in the XZ
half-plane (X >= 0) revolved around the Z axis, with a parallel cavity
profile subtracted to produce wall thickness.

This module exposes ``revolved_shell``, which takes:
  - the outer profile as a list of (r, z) points (CCW closed polygon)
  - the cavity profile as a list of (r, z) points (CCW closed polygon),
    which the caller computes by inset = outer minus wall offset
  - returns the resulting CadQuery Workplane

Templates that have non-uniform wall behavior (a thicker base, a foot, etc.)
build their cavity profiles by hand. The helper exists for the cavity-IS-
present case, not to invent a one-size-fits-all offset routine — offsetting
arbitrary 2D profiles correctly is hard and not worth the complexity here.
"""

from __future__ import annotations

import cadquery as cq


def revolve_profile(points: list[tuple[float, float]]) -> cq.Workplane:
    """Revolve a CCW closed (r, z) polygon around the Z axis."""
    return (
        cq.Workplane("XZ")
        .polyline(points)
        .close()
        .revolve(360)
    )


def revolved_shell(
    outer: list[tuple[float, float]],
    cavity: list[tuple[float, float]] | None,
) -> cq.Workplane:
    """Build a revolved shell: outer profile minus optional cavity profile.

    Both profiles must be closed CCW polygons in the XZ half-plane.
    cavity=None produces a solid (no internal volume removed) — useful for
    foot bases and very small forms where shelling produces invalid geometry.
    """
    solid = revolve_profile(outer)
    if cavity is not None:
        # Guard against degenerate cavity polygons — fewer than 3 points
        # cannot form a closed face. Caller is supposed to check, but a
        # belt-and-braces guard here makes templates safer.
        if len(cavity) < 3:
            return solid
        solid = solid.cut(revolve_profile(cavity))
    return solid
