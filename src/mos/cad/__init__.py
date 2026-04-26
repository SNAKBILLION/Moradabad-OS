"""CAD stage: template dispatch, build, shrinkage, export, DFM checking.

Import from here; submodule layout is an implementation detail. The
``run_cad`` function is the only public entry point; ``check``, ``compute_metrics``
and ``load_dfm_rules`` are exposed for testing and for modules that want to
re-run DFM without rebuilding geometry.
"""

from __future__ import annotations

from .dfm import GeometryMetrics, check, compute_metrics
from .rules import DfmRules, SandCastingRules, load_dfm_rules
from .runner import (
    CadResult,
    TemplateNotRegisteredError,
    TemplateRegistry,
    run_cad,
)

__all__ = [
    "CadResult",
    "DfmRules",
    "GeometryMetrics",
    "SandCastingRules",
    "TemplateNotRegisteredError",
    "TemplateRegistry",
    "check",
    "compute_metrics",
    "load_dfm_rules",
    "run_cad",
]
