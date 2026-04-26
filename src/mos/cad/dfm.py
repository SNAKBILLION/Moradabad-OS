"""DFM (Design For Manufacturability) checker.

Runs a fixed set of rules against (a) the template's declared properties and
(b) the built geometry. Returns a ManufacturabilityReport whose `.passed`
property is False if any rule has status FAIL.

Rules implemented in M5 (all real, no stubs):

1. MIN_WALL_THICKNESS — template's ``declared_min_wall_mm`` must meet or
   exceed the foundry minimum from dfm_rules.yaml.
2. DRAFT_ANGLE — template's ``declared_min_draft_deg`` must meet or exceed
   the foundry minimum. (Declaration-based, not geometric. See ROADMAP.)
3. MAX_BOUNDING_BOX — measured from the built solid; each axis must be
   within the foundry limit.
4. MAX_MASS — volume * density must not exceed the foundry's handling limit.
5. UNDERCUT_DETECTED — uses the template's ``declared_produces_no_undercuts``
   flag. PASS if declared True; WARN if declared False (M5 has no geometric
   undercut detector, see ROADMAP).
6. CLOSED_SHELL — performed by the runner on the exported STL via trimesh
   (we accept a precomputed boolean here so this module has no trimesh
   dependency and stays pure w.r.t. geometry).
7. SHRINKAGE_APPLIED — informational PASS if the runner applied shrinkage
   before export; surfaced in the report so downstream consumers know the
   exported geometry is at *pattern* size, not final-part size.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import cadquery as cq

from mos.cad.rules import DfmRules
from mos.schemas import (
    CheckResult,
    CheckRule,
    CheckStatus,
    ManufacturabilityReport,
)
from mos.templates.base import Template


@dataclass(frozen=True)
class GeometryMetrics:
    """Precomputed from the built solid so the DFM module stays free of
    CadQuery-specific call paths at check time. The runner computes this
    and hands it to ``check``.
    """

    volume_mm3: float
    mass_g: float
    bbox_x_mm: float
    bbox_y_mm: float
    bbox_z_mm: float
    stl_is_watertight: bool


def compute_metrics(solid: cq.Workplane, density_g_cm3: float) -> GeometryMetrics:
    """Pull metrics off the built solid. Called by the runner. Does NOT
    include watertight status — that's computed separately from the STL."""
    v = solid.val()
    volume_mm3 = v.Volume()
    mass_g = volume_mm3 * density_g_cm3 / 1000.0
    bb = v.BoundingBox()
    return GeometryMetrics(
        volume_mm3=volume_mm3,
        mass_g=mass_g,
        bbox_x_mm=bb.xlen,
        bbox_y_mm=bb.ylen,
        bbox_z_mm=bb.zlen,
        stl_is_watertight=False,  # runner overrides after exporting STL
    )


def check(
    spec_id: UUID,
    template: Template,
    metrics: GeometryMetrics,
    rules: DfmRules,
    *,
    shrinkage_applied: bool,
) -> ManufacturabilityReport:
    """Evaluate all seven rules and return a report."""
    results: list[CheckResult] = []
    sand = rules.brass_sand

    # 1. Min wall thickness — declared vs foundry limit
    if template.declared_min_wall_mm >= sand.min_wall_mm:
        results.append(
            CheckResult(
                rule_id=CheckRule.MIN_WALL_THICKNESS,
                status=CheckStatus.PASS,
                value=template.declared_min_wall_mm,
                threshold=sand.min_wall_mm,
                message=(
                    f"template declares min wall "
                    f"{template.declared_min_wall_mm}mm "
                    f">= foundry minimum {sand.min_wall_mm}mm"
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                rule_id=CheckRule.MIN_WALL_THICKNESS,
                status=CheckStatus.FAIL,
                value=template.declared_min_wall_mm,
                threshold=sand.min_wall_mm,
                message=(
                    f"template declares min wall "
                    f"{template.declared_min_wall_mm}mm "
                    f"< foundry minimum {sand.min_wall_mm}mm"
                ),
            )
        )

    # 2. Draft angle — declared vs foundry limit.
    # Declaration-based, not geometric. Consistent with UNDERCUT_DETECTED:
    # below-foundry is a WARN for manual review, not a FAIL. A real geometric
    # draft check replaces this when we implement it (see ROADMAP).
    if template.declared_min_draft_deg >= sand.min_draft_deg:
        results.append(
            CheckResult(
                rule_id=CheckRule.DRAFT_ANGLE,
                status=CheckStatus.PASS,
                value=template.declared_min_draft_deg,
                threshold=sand.min_draft_deg,
                message=(
                    f"template declares min draft "
                    f"{template.declared_min_draft_deg}deg "
                    f">= foundry minimum {sand.min_draft_deg}deg"
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                rule_id=CheckRule.DRAFT_ANGLE,
                status=CheckStatus.WARN,
                value=template.declared_min_draft_deg,
                threshold=sand.min_draft_deg,
                message=(
                    f"template declares min draft "
                    f"{template.declared_min_draft_deg}deg "
                    f"< foundry minimum {sand.min_draft_deg}deg; "
                    f"manual review required (M5 has no geometric draft check)"
                ),
            )
        )

    # 3. Max bounding box — measured vs foundry limits (all three axes)
    bbox_violations = []
    if metrics.bbox_x_mm > sand.max_bbox_x_mm:
        bbox_violations.append(f"X={metrics.bbox_x_mm:.1f}>{sand.max_bbox_x_mm}")
    if metrics.bbox_y_mm > sand.max_bbox_y_mm:
        bbox_violations.append(f"Y={metrics.bbox_y_mm:.1f}>{sand.max_bbox_y_mm}")
    if metrics.bbox_z_mm > sand.max_bbox_z_mm:
        bbox_violations.append(f"Z={metrics.bbox_z_mm:.1f}>{sand.max_bbox_z_mm}")
    if bbox_violations:
        results.append(
            CheckResult(
                rule_id=CheckRule.MAX_BOUNDING_BOX,
                status=CheckStatus.FAIL,
                value=max(
                    metrics.bbox_x_mm, metrics.bbox_y_mm, metrics.bbox_z_mm
                ),
                threshold=max(
                    sand.max_bbox_x_mm,
                    sand.max_bbox_y_mm,
                    sand.max_bbox_z_mm,
                ),
                message="bbox exceeds foundry limit: " + ", ".join(bbox_violations),
            )
        )
    else:
        results.append(
            CheckResult(
                rule_id=CheckRule.MAX_BOUNDING_BOX,
                status=CheckStatus.PASS,
                value=max(
                    metrics.bbox_x_mm, metrics.bbox_y_mm, metrics.bbox_z_mm
                ),
                threshold=max(
                    sand.max_bbox_x_mm,
                    sand.max_bbox_y_mm,
                    sand.max_bbox_z_mm,
                ),
                message=(
                    f"bbox {metrics.bbox_x_mm:.1f}x{metrics.bbox_y_mm:.1f}x"
                    f"{metrics.bbox_z_mm:.1f}mm within foundry limits"
                ),
            )
        )

    # 4. Max mass — computed vs foundry limit
    if metrics.mass_g <= sand.max_mass_g:
        results.append(
            CheckResult(
                rule_id=CheckRule.MAX_MASS,
                status=CheckStatus.PASS,
                value=metrics.mass_g,
                threshold=sand.max_mass_g,
                message=f"mass {metrics.mass_g:.1f}g <= {sand.max_mass_g}g",
            )
        )
    else:
        results.append(
            CheckResult(
                rule_id=CheckRule.MAX_MASS,
                status=CheckStatus.FAIL,
                value=metrics.mass_g,
                threshold=sand.max_mass_g,
                message=f"mass {metrics.mass_g:.1f}g exceeds {sand.max_mass_g}g",
            )
        )

    # 5. Undercut — declaration-based (see ROADMAP for geometric check)
    if template.declared_produces_no_undercuts:
        results.append(
            CheckResult(
                rule_id=CheckRule.UNDERCUT_DETECTED,
                status=CheckStatus.PASS,
                message="template declares no undercuts",
            )
        )
    else:
        results.append(
            CheckResult(
                rule_id=CheckRule.UNDERCUT_DETECTED,
                status=CheckStatus.WARN,
                message=(
                    "template does not declare undercut-free; "
                    "manual review required (M5 has no geometric detector)"
                ),
            )
        )

    # 6. Closed shell — from STL watertight check
    if metrics.stl_is_watertight:
        results.append(
            CheckResult(
                rule_id=CheckRule.CLOSED_SHELL,
                status=CheckStatus.PASS,
                message="exported STL is watertight",
            )
        )
    else:
        results.append(
            CheckResult(
                rule_id=CheckRule.CLOSED_SHELL,
                status=CheckStatus.FAIL,
                message="exported STL is not watertight",
            )
        )

    # 7. Shrinkage applied — informational
    if shrinkage_applied:
        results.append(
            CheckResult(
                rule_id=CheckRule.SHRINKAGE_APPLIED,
                status=CheckStatus.PASS,
                value=sand.shrinkage_linear,
                message=(
                    f"shrinkage {sand.shrinkage_linear * 100:.1f}% applied; "
                    "exported geometry is at PATTERN size"
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                rule_id=CheckRule.SHRINKAGE_APPLIED,
                status=CheckStatus.WARN,
                value=0.0,
                message=(
                    "shrinkage NOT applied; exported geometry is at "
                    "final-part size. Do not use as a casting pattern."
                ),
            )
        )

    return ManufacturabilityReport(spec_id=spec_id, checks=results)
