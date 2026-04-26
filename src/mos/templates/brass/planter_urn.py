"""Planter, urn profile.

Classic urn: narrow base, swelling to wider shoulders, narrowing to a
moderate rim. The shoulders create an undercut from the top parting line
perspective — this form CANNOT be cleanly sand-cast as one piece. Real
production splits it into two halves cast separately and welded, or uses
lost-wax for the whole thing.

We declare ``declared_produces_no_undercuts = False`` so the DFM check
emits a WARN (per the M5 design — declaration-based rules WARN rather than
FAIL). The factory operator sees the warning and decides whether to:
  - cast in two halves and weld the joint along the equator
  - switch to lost-wax for low-volume runs
  - reject the design and pick a non-urn alternative

This is intentional: archetypes shouldn't be over-constrained to hide the
forms that the industry actually wants. The system surfaces the
manufacturing tradeoff.
"""

from __future__ import annotations

import cadquery as cq

from mos.templates.base import ParamSpec
from mos.templates.brass._revolve import revolved_shell


class PlanterUrn:
    template_id = "planter_urn_v1"
    version = "1.0.0"
    product_family = "planter"
    description = (
        "Classic urn-profile planter. Has shoulder undercut — production "
        "may require two-piece cast + weld, or lost-wax."
    )

    param_schema = (
        ParamSpec(
            name="base_diameter",
            description="Outer diameter at the base.",
            min_mm=60.0,
            max_mm=160.0,
        ),
        ParamSpec(
            name="shoulder_diameter",
            description="Maximum outer diameter at the shoulder.",
            min_mm=120.0,
            max_mm=320.0,
        ),
        ParamSpec(
            name="rim_diameter",
            description="Outer diameter at the rim (top opening).",
            min_mm=70.0,
            max_mm=200.0,
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

    regions = ("body", "shoulder", "neck", "rim", "base")
    declared_min_wall_mm = 3.0
    declared_min_draft_deg = 1.5
    declared_produces_no_undercuts = False  # shoulder undercut by design

    def build(self, params: dict[str, float]) -> cq.Workplane:
        base_r = params["base_diameter"] / 2.0
        shoulder_r = params["shoulder_diameter"] / 2.0
        rim_r = params["rim_diameter"] / 2.0
        height = params["height"]
        wall = params["wall_thickness"]

        # Shoulder is at 60% height; gentle waist below; neck above.
        shoulder_z = height * 0.60
        waist_z = height * 0.30
        # Waist radius: slightly smaller than base, characteristic of urn.
        waist_r = base_r + (shoulder_r - base_r) * 0.20
        # Neck below the rim — slight inward curve before the rim.
        neck_z = height * 0.85
        neck_r = (shoulder_r + rim_r) / 2.0

        outer = [
            (0.0, 0.0),
            (base_r, 0.0),
            (waist_r, waist_z),
            (shoulder_r, shoulder_z),
            (neck_r, neck_z),
            (rim_r, height),
            (0.0, height),
        ]

        # Cavity inset uniformly by wall.
        cavity_z_start = wall
        cavity_z_end = height - wall
        cavity = [
            (0.0, cavity_z_start),
            (max(base_r - wall, 0.1), cavity_z_start),
            (max(waist_r - wall, 0.1), waist_z),
            (max(shoulder_r - wall, 0.1), shoulder_z),
            (max(neck_r - wall, 0.1), neck_z),
            (max(rim_r - wall, 0.1), cavity_z_end),
            (0.0, cavity_z_end),
        ]
        return revolved_shell(outer, cavity)
