"""Parametric templates.

A template is a pure-function (params -> Workplane) implementing the
``Template`` protocol from ``base``. Concrete templates live in material
subpackages (e.g. ``brass/``). The runner consumes a ``TemplateRegistry``
mapping ``template_id`` to an instance.

This module exposes ``default_registry()``, which returns every registered
template so callers don't have to import each one by hand. The order of
entries is stable so ``PipelineSnapshot`` replay produces consistent IDs
when a template id collides (which it shouldn't — IDs are unique by design).
"""

from __future__ import annotations

from .base import (
    ParamSpec,
    Template,
    TemplateParamError,
    template_metadata,
    validate_params,
)
from .brass.bowl_footed import BowlFooted
from .brass.bowl_spheroid import BowlSpheroid
from .brass.candle_holder_classic import CandleHolderClassic
from .brass.candle_holder_pillar import CandleHolderPillar
from .brass.candle_holder_taperstem import CandleHolderTaperStem
from .brass.planter_bell import PlanterBell
from .brass.planter_cylinder import PlanterCylinder
from .brass.planter_urn import PlanterUrn
from .brass.vase_baluster import VaseBaluster
from .brass.vase_trumpet import VaseTrumpet


def default_registry() -> dict[str, Template]:
    """All Phase 1 archetypes, indexed by template_id.

    Ten public archetypes covering the four product families. Forms are
    derived from canonical Moradabad export shapes (bell planter, baluster
    vase, footed bowl, etc.) — public product types, not factory SKUs.
    """
    instances: list[Template] = [
        CandleHolderClassic(),
        CandleHolderPillar(),
        CandleHolderTaperStem(),
        PlanterBell(),
        PlanterCylinder(),
        PlanterUrn(),
        VaseBaluster(),
        VaseTrumpet(),
        BowlSpheroid(),
        BowlFooted(),
    ]
    registry: dict[str, Template] = {}
    for t in instances:
        if t.template_id in registry:
            raise RuntimeError(
                f"duplicate template_id in registry: {t.template_id!r}"
            )
        registry[t.template_id] = t
    return registry


__all__ = [
    "ParamSpec",
    "Template",
    "TemplateParamError",
    "default_registry",
    "template_metadata",
    "validate_params",
]
