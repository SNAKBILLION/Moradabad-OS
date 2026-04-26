"""Brass-material templates for Phase 1.

Ten archetype templates covering candle holders, planters, vases, and bowls.
Two forms have declared undercuts (urn planter, baluster vase) — see those
modules' docstrings for the manufacturing implication.
"""

from .bowl_footed import BowlFooted
from .bowl_spheroid import BowlSpheroid
from .candle_holder_classic import CandleHolderClassic
from .candle_holder_pillar import CandleHolderPillar
from .candle_holder_taperstem import CandleHolderTaperStem
from .planter_bell import PlanterBell
from .planter_cylinder import PlanterCylinder
from .planter_urn import PlanterUrn
from .vase_baluster import VaseBaluster
from .vase_trumpet import VaseTrumpet

__all__ = [
    "BowlFooted",
    "BowlSpheroid",
    "CandleHolderClassic",
    "CandleHolderPillar",
    "CandleHolderTaperStem",
    "PlanterBell",
    "PlanterCylinder",
    "PlanterUrn",
    "VaseBaluster",
    "VaseTrumpet",
]
