"""DesignSpec: the structured output of the intent layer.

This is the canonical input for the CAD layer. The LLM never emits geometry
directly; it emits a DesignSpec (or returns template_id=None to halt the
pipeline for human review).

Schema version starts at "1.0". Bump on breaking changes; maintain a
migration path in intent.migrations when we ever need it.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .common import (
    BrassAlloy,
    CastingMethod,
    Measurement,
    Money,
    Plating,
    PolishFinish,
    ProductFamily,
)

SCHEMA_VERSION = "1.0"


# --- Sub-specs -----------------------------------------------------------

# Density g/cm^3 for each brass alloy. Source: ASM Handbook, standard values.
# Kept in code (not config) because these are physical constants, not
# factory-tunable parameters.
_ALLOY_DENSITY_G_CM3: dict[BrassAlloy, float] = {
    BrassAlloy.BRASS_70_30: 8.53,
    BrassAlloy.BRASS_85_15: 8.75,
    BrassAlloy.BRASS_65_35: 8.47,
}

# Minimum wall thickness (mm) for sand casting per alloy. Conservative
# values from foundry practice; factory may override via config/dfm_rules.yaml
# once Phase 1 calibration begins.
_ALLOY_MIN_WALL_SAND_MM: dict[BrassAlloy, float] = {
    BrassAlloy.BRASS_70_30: 3.0,
    BrassAlloy.BRASS_85_15: 3.0,
    BrassAlloy.BRASS_65_35: 3.0,
}


class MaterialSpec(BaseModel):
    """Material selection with derived physical properties.

    density_g_cm3 and min_wall_mm are derived from the alloy + casting method;
    they are never accepted as free input from the LLM.
    """

    model_config = ConfigDict(frozen=True)

    alloy: BrassAlloy
    casting_method: CastingMethod
    density_g_cm3: float = Field(gt=0)
    min_wall_mm: float = Field(gt=0)

    @model_validator(mode="after")
    def _check_derived_fields(self) -> MaterialSpec:
        expected_density = _ALLOY_DENSITY_G_CM3[self.alloy]
        if abs(self.density_g_cm3 - expected_density) > 1e-6:
            raise ValueError(
                f"density_g_cm3 for {self.alloy.value} must be "
                f"{expected_density}, got {self.density_g_cm3}"
            )
        # Phase 1: only sand casting has a derived min_wall.
        # Lost-wax values will be added when that template lands.
        if self.casting_method == CastingMethod.SAND:
            expected_min_wall = _ALLOY_MIN_WALL_SAND_MM[self.alloy]
            if abs(self.min_wall_mm - expected_min_wall) > 1e-6:
                raise ValueError(
                    f"min_wall_mm for {self.alloy.value} + sand casting "
                    f"must be {expected_min_wall}, got {self.min_wall_mm}"
                )
        return self

    @classmethod
    def for_alloy(
        cls, alloy: BrassAlloy, casting_method: CastingMethod = CastingMethod.SAND
    ) -> MaterialSpec:
        """Helper: construct a MaterialSpec from an alloy with defaults."""
        if casting_method != CastingMethod.SAND:
            # Phase 1 guard: lost-wax values not yet defined.
            raise NotImplementedError(
                "Only sand casting is supported in Phase 1"
            )
        return cls(
            alloy=alloy,
            casting_method=casting_method,
            density_g_cm3=_ALLOY_DENSITY_G_CM3[alloy],
            min_wall_mm=_ALLOY_MIN_WALL_SAND_MM[alloy],
        )


class FinishSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    polish: PolishFinish
    plating: Plating = Plating.NONE
    lacquer: bool = False
    patina: str | None = None  # free-form name; resolved in finish library later

    @field_validator("patina")
    @classmethod
    def _patina_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 64:
            raise ValueError("patina name must be <= 64 chars")
        return v


class MotifRef(BaseModel):
    """Reference to a motif in the motif library + where it is placed."""

    model_config = ConfigDict(frozen=True)

    motif_id: str = Field(min_length=1, max_length=128)
    placement_region: str = Field(min_length=1, max_length=64)
    # Regions are template-specific (e.g. "body", "rim", "base"). The CAD
    # layer validates that the region exists on the chosen template.


# --- DesignSpec ----------------------------------------------------------

class DesignSpec(BaseModel):
    """Structured design intent produced by the LLM, consumed by CAD.

    template_id=None is a valid terminal state: it means the LLM could not
    match the brief to an existing template. The orchestrator halts the job
    in awaiting_review; no CAD is attempted.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(default=SCHEMA_VERSION)
    spec_id: UUID = Field(default_factory=uuid4)
    brief_id: UUID
    product_family: ProductFamily
    template_id: str | None
    dimensions: dict[str, Measurement] = Field(default_factory=dict)
    material: MaterialSpec
    finish: FinishSpec
    motif_refs: list[MotifRef] = Field(default_factory=list)
    quantity: Annotated[int, Field(ge=1, le=100_000)]
    target_unit_cost: Money | None = None
    buyer_notes: str = Field(default="", max_length=4000)

    @field_validator("schema_version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if v != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported schema_version {v}; expected {SCHEMA_VERSION}"
            )
        return v

    @model_validator(mode="after")
    def _check_template_null_means_no_dimensions(self) -> DesignSpec:
        # If the LLM couldn't pick a template, dimensions are meaningless.
        # Reject the confusing middle state early.
        if self.template_id is None and self.dimensions:
            raise ValueError(
                "dimensions must be empty when template_id is None"
            )
        return self
