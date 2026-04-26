"""Vase, baluster profile.

Baluster: bulbous body with a narrow neck and a flared rim. Like the urn,
this form has an undercut (the body is wider than the neck and rim) and
cannot be sand-cast as one piece without splitting or using lost-wax.

Declared via ``declared_produces_no_undercuts = False`` so the DFM check
WARNs the operator. See planter_urn.py for the longer rationale.
"""

from __future__ import annotations

import cadquery as cq

from mos.templates.base import ParamSpec
from mos.templates.brass._revolve import revolved_shell


class VaseBaluster:
    template_id = "vase_baluster_v1"
    version = "1.0.0"
    product_family = "vase"
    description = (
        "Baluster-profile vase with bulbous body and narrow neck. Has "
        "undercut — production typically uses lost-wax casting."
    )

    param_schema = (
        ParamSpec(
            name="base_diameter",
            description="Outer diameter at the base.",
            min_mm=40.0,
            max_mm=140.0,
        ),
        ParamSpec(
            name="body_diameter",
            description="Maximum outer diameter at the body bulge.",
            min_mm=80.0,
            max_mm=220.0,
        ),
        ParamSpec(
            name="neck_diameter",
            description="Outer diameter at the narrow neck.",
            min_mm=30.0,
            max_mm=80.0,
        ),
        ParamSpec(
            name="rim_diameter",
            description="Outer diameter at the rim (slight flare).",
            min_mm=40.0,
            max_mm=120.0,
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

    regions = ("body", "neck", "rim", "base")
    declared_min_wall_mm = 3.0
    declared_min_draft_deg = 1.5
    declared_produces_no_undercuts = False

    def build(self, params: dict[str, float]) -> cq.Workplane:
        base_r = params["base_diameter"] / 2.0
        body_r = params["body_diameter"] / 2.0
        neck_r = params["neck_diameter"] / 2.0
        rim_r = params["rim_diameter"] / 2.0
        height = params["height"]
        wall = params["wall_thickness"]

        # Body bulge at 35% height, neck at 75%, rim at 100%.
        body_z = height * 0.35
        neck_z = height * 0.75

        outer = [
            (0.0, 0.0),
            (base_r, 0.0),
            (body_r, body_z),
            (neck_r, neck_z),
            (rim_r, height),
            (0.0, height),
        ]

        cavity_z_start = wall
        cavity_z_end = height - wall
        cavity = [
            (0.0, cavity_z_start),
            (max(base_r - wall, 0.1), cavity_z_start),
            (max(body_r - wall, 0.1), body_z),
            (max(neck_r - wall, 0.1), neck_z),
            (max(rim_r - wall, 0.1), cavity_z_end),
            (0.0, cavity_z_end),
        ]
        return revolved_shell(outer, cavity)
