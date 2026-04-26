"""CAD runner.

Orchestrates one CAD stage of the pipeline:

    DesignSpec -> Template lookup -> param validation -> build -> shrinkage
    -> export STEP + STL -> watertight check -> DFM report

The runner is deterministic: same DesignSpec + same template version + same
DFM rules version -> same STEP and STL bytes (subject to CadQuery/OCCT
determinism, which is reliable in practice for fixed inputs).

Inputs and outputs are explicit; no global state, no side effects beyond
writing the two output files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import cadquery as cq
import trimesh

from mos.cad.dfm import GeometryMetrics, check, compute_metrics
from mos.cad.rules import DfmRules, load_dfm_rules
from mos.schemas import DesignSpec, ManufacturabilityReport
from mos.templates.base import Template, TemplateParamError, validate_params


@dataclass(frozen=True)
class CadResult:
    step_path: Path
    stl_path: Path
    report: ManufacturabilityReport
    metrics: GeometryMetrics  # final metrics including watertight flag
    shrinkage_applied: bool


class TemplateNotRegisteredError(LookupError):
    """DesignSpec references a template_id that isn't in the registry."""


TemplateRegistry = Mapping[str, Template]


def run_cad(
    spec: DesignSpec,
    registry: TemplateRegistry,
    output_dir: Path,
    *,
    apply_shrinkage: bool = True,
    rules: DfmRules | None = None,
) -> CadResult:
    """Run the CAD stage for one spec. Raises if the spec is un-buildable
    (unknown template, missing params, out-of-range values); returns a
    CadResult with a ManufacturabilityReport otherwise.

    The report may contain FAIL results. The caller decides whether a FAIL
    halts the pipeline — this function's job is to produce the report
    honestly, not to interpret it.
    """
    if spec.template_id is None:
        raise ValueError(
            "DesignSpec has template_id=None; CAD stage cannot proceed. "
            "The orchestrator should halt the job in awaiting_review."
        )

    template = registry.get(spec.template_id)
    if template is None:
        raise TemplateNotRegisteredError(
            f"template {spec.template_id!r} not in registry "
            f"(available: {sorted(registry.keys())})"
        )

    # Extract numeric params from the spec's Measurement objects.
    params = {name: m.value for name, m in spec.dimensions.items()}
    validate_params(template, params)  # raises TemplateParamError on mismatch

    dfm_rules = rules or load_dfm_rules()

    # Build at final-part size.
    solid = template.build(params)

    # Apply shrinkage if requested. We take a pre-shrinkage metrics snapshot
    # for the DFM bbox/mass rules because the foundry limits refer to the
    # final part, not the pattern. Mass in particular: the foundry cares
    # about the mass of metal poured (pattern-determined), but for Phase 1
    # we report final-part mass because the density we have is brass, and
    # the pattern isn't made of brass — it's sand or wax. We want the
    # finished-part mass; that's what the customer buys.
    metrics_presrink = compute_metrics(solid, spec.material.density_g_cm3)

    if apply_shrinkage:
        shrink = dfm_rules.brass_sand.shrinkage_linear
        scaled_shape = solid.val().scale(1.0 + shrink)
        # Wrap back into a Workplane so the exporter API is consistent.
        export_solid = cq.Workplane(obj=scaled_shape)
        shrinkage_applied = True
    else:
        export_solid = solid
        shrinkage_applied = False

    # Export. Tolerances are pinned explicitly so the output is deterministic
    # across OCCT versions — default tolerances can drift between releases.
    # STL values below are in mm. STEP doesn't tessellate so it's unaffected
    # by these, but we still export it through the same call shape.
    output_dir.mkdir(parents=True, exist_ok=True)
    step_path = output_dir / f"{spec.spec_id}.step"
    stl_path = output_dir / f"{spec.spec_id}.stl"
    cq.exporters.export(export_solid, str(step_path), exportType="STEP")
    cq.exporters.export(
        export_solid,
        str(stl_path),
        exportType="STL",
        tolerance=0.01,          # linear deflection, mm
        angularTolerance=0.1,    # radians
    )

    # Watertight check on the exported STL.
    mesh = trimesh.load(str(stl_path))
    watertight = bool(mesh.is_watertight)

    # Final metrics used by DFM: final-part dimensions and mass (not pattern).
    metrics_final = GeometryMetrics(
        volume_mm3=metrics_presrink.volume_mm3,
        mass_g=metrics_presrink.mass_g,
        bbox_x_mm=metrics_presrink.bbox_x_mm,
        bbox_y_mm=metrics_presrink.bbox_y_mm,
        bbox_z_mm=metrics_presrink.bbox_z_mm,
        stl_is_watertight=watertight,
    )

    report = check(
        spec_id=spec.spec_id,
        template=template,
        metrics=metrics_final,
        rules=dfm_rules,
        shrinkage_applied=shrinkage_applied,
    )

    return CadResult(
        step_path=step_path,
        stl_path=stl_path,
        report=report,
        metrics=metrics_final,
        shrinkage_applied=shrinkage_applied,
    )
