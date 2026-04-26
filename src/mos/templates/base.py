"""Template base contract.

Every parametric template in ``mos.templates.*`` implements ``Template``.
The contract is intentionally small:

- ``template_id`` and ``version`` uniquely identify the template + revision.
- ``param_schema`` declares which dimensions the template expects. The runner
  uses this to validate a DesignSpec against the template before building.
- ``regions`` is the list of motif placement regions the template supports.
  Motif refs in a DesignSpec must name a region that appears here.
- ``declared_min_wall_mm`` and ``declared_min_draft_deg`` are the
  template-author's promises about its geometry. DFM rules validate these
  against foundry limits; we do not re-measure them from the built solid
  (see ROADMAP for the geometric-check deferral).
- ``declared_produces_no_undercuts`` is a self-declared flag, same rationale.
- ``build(params)`` returns a CadQuery Workplane at *final part* size (no
  shrinkage). The runner applies the shrinkage scale at export time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import cadquery as cq


@dataclass(frozen=True)
class ParamSpec:
    """One parameter declared by a template.

    min_mm / max_mm are the template-author's bounds, not foundry DFM bounds.
    The runner rejects spec dimensions outside this range before building
    so we never attempt to build geometry the template can't support.
    """

    name: str
    description: str
    min_mm: float
    max_mm: float


@runtime_checkable
class Template(Protocol):
    template_id: str
    version: str
    product_family: str
    description: str
    param_schema: tuple[ParamSpec, ...]
    regions: tuple[str, ...]

    # Template-author declarations validated by DFM rules.
    declared_min_wall_mm: float
    declared_min_draft_deg: float
    declared_produces_no_undercuts: bool

    def build(self, params: dict[str, float]) -> cq.Workplane:
        """Build the final-part geometry (no shrinkage applied).

        Must be deterministic: same params -> same geometry every call.
        """
        ...


class TemplateParamError(ValueError):
    """Raised when a DesignSpec's dimensions don't match a template's
    param_schema (missing params, extras, out-of-range values)."""


def validate_params(
    template: Template, params: dict[str, float]
) -> None:
    """Validate params against a template's schema. Raises TemplateParamError.

    Checks:
    - every declared param is present
    - no undeclared params are passed
    - every value is within the template's declared min/max
    """
    declared = {p.name: p for p in template.param_schema}
    declared_names = set(declared.keys())
    provided_names = set(params.keys())

    missing = declared_names - provided_names
    if missing:
        raise TemplateParamError(
            f"template {template.template_id}: missing params "
            f"{sorted(missing)}"
        )
    extra = provided_names - declared_names
    if extra:
        raise TemplateParamError(
            f"template {template.template_id}: unexpected params "
            f"{sorted(extra)}"
        )
    for name, value in params.items():
        spec = declared[name]
        if not (spec.min_mm <= value <= spec.max_mm):
            raise TemplateParamError(
                f"template {template.template_id}: param {name}={value}mm "
                f"outside declared range [{spec.min_mm}, {spec.max_mm}]"
            )


def template_metadata(template: Template) -> dict[str, Any]:
    """Pure helper: produces a JSON-serializable dict describing the template.
    Used by TemplateRow in the DB and by PipelineSnapshot for audit."""
    return {
        "template_id": template.template_id,
        "version": template.version,
        "product_family": template.product_family,
        "description": template.description,
        "param_schema": [
            {
                "name": p.name,
                "description": p.description,
                "min_mm": p.min_mm,
                "max_mm": p.max_mm,
            }
            for p in template.param_schema
        ],
        "regions": list(template.regions),
        "declared_min_wall_mm": template.declared_min_wall_mm,
        "declared_min_draft_deg": template.declared_min_draft_deg,
        "declared_produces_no_undercuts": template.declared_produces_no_undercuts,
    }
