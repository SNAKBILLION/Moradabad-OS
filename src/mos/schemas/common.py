"""Common types shared across schema modules.

All domain enums and primitive value objects live here so that higher-level
schemas (DesignSpec, CostSheet, etc.) can compose them without import cycles.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --- Enums ---------------------------------------------------------------

class ProductFamily(str, Enum):
    """Phase 1 product families. Rotationally-symmetric, brass, cast."""

    CANDLE_HOLDER = "candle_holder"
    PLANTER = "planter"
    VASE = "vase"
    BOWL = "bowl"
    TEALIGHT_HOLDER = "tealight_holder"


class BrassAlloy(str, Enum):
    """Brass alloys supported in Phase 1.

    Naming is Cu/Zn percentage. Density values are applied by MaterialSpec
    validators, not stored on the enum.
    """

    BRASS_70_30 = "brass_70_30"  # cartridge brass
    BRASS_85_15 = "brass_85_15"  # red / gilding brass
    BRASS_65_35 = "brass_65_35"  # yellow / common Moradabad sand-cast


class CastingMethod(str, Enum):
    SAND = "sand"
    LOST_WAX = "lost_wax"


class PolishFinish(str, Enum):
    MIRROR = "mirror"
    SATIN = "satin"
    MATTE = "matte"
    ANTIQUE = "antique"
    HAMMERED = "hammered"


class Plating(str, Enum):
    NONE = "none"
    NICKEL = "nickel"
    SILVER = "silver"
    GOLD = "gold"


class Currency(str, Enum):
    INR = "INR"
    USD = "USD"


# --- Value objects -------------------------------------------------------

class Measurement(BaseModel):
    """A scalar measurement with unit. Phase 1 uses mm only for geometry."""

    model_config = ConfigDict(frozen=True)

    value: float = Field(gt=0)
    unit: str = Field(pattern=r"^(mm|cm|g|kg)$")


class Money(BaseModel):
    """Monetary amount. Stored as float for Phase 1; if rounding bugs appear
    during factory calibration, migrate to Decimal before Phase 2."""

    model_config = ConfigDict(frozen=True)

    value: float = Field(ge=0)
    currency: Currency

    @field_validator("value")
    @classmethod
    def _round_to_paisa(cls, v: float) -> float:
        # Two-decimal precision matches how factory owners actually quote.
        return round(v, 2)
