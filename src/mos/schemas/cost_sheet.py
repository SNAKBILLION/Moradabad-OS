"""CostSheet: output of the cost engine.

Every CostSheet is self-describing — a reviewer can reconstruct the totals
from the line items alone. metal_rate_used and fx_used record the exact
external data that was fetched for this calculation, which is essential for
the reproducibility guarantee.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import Currency, Money


class LineItemCode(str, Enum):
    RAW_BRASS = "RAW_BRASS"
    CASTING_LABOR = "CASTING_LABOR"
    SCRAPING_LABOR = "SCRAPING_LABOR"
    CHASING_LABOR = "CHASING_LABOR"
    POLISHING = "POLISHING"
    LACQUER = "LACQUER"
    PLATING = "PLATING"
    PACKING = "PACKING"
    OVERHEAD = "OVERHEAD"
    MARGIN = "MARGIN"
    FREIGHT_INLAND = "FREIGHT_INLAND"
    FREIGHT_OCEAN = "FREIGHT_OCEAN"


class CostLineItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: LineItemCode
    description: str = Field(max_length=200)
    qty: float = Field(ge=0)
    unit: str = Field(max_length=16)  # "g", "min", "piece", "lot"
    unit_rate_inr: float = Field(ge=0)
    amount_inr: float = Field(ge=0)

    @model_validator(mode="after")
    def _amount_matches_qty_times_rate(self) -> CostLineItem:
        expected = round(self.qty * self.unit_rate_inr, 2)
        # Tolerance covers accumulated float error in upstream calculation.
        if abs(expected - self.amount_inr) > 0.01:
            raise ValueError(
                f"{self.code.value}: amount_inr={self.amount_inr} "
                f"does not match qty*unit_rate={expected}"
            )
        return self


class MetalRate(BaseModel):
    """Snapshot of the metal rate used for this sheet."""

    model_config = ConfigDict(frozen=True)

    rate_per_kg_inr: float = Field(gt=0)
    source: str = Field(min_length=1, max_length=64)  # e.g. "ibja", "manual"
    fetched_at: datetime
    stale: bool = False  # true if we fell back to cache


class FxSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    inr_to_usd: float = Field(gt=0)
    source: str = Field(min_length=1, max_length=64)
    fetched_at: datetime


class CostTotals(BaseModel):
    model_config = ConfigDict(frozen=True)

    ex_factory_inr: float = Field(ge=0)
    fob_moradabad_inr: float = Field(ge=0)
    fob_moradabad_usd: float = Field(ge=0)
    cif_target_port_usd: float | None = None

    @model_validator(mode="after")
    def _fob_gte_exfactory(self) -> CostTotals:
        if self.fob_moradabad_inr < self.ex_factory_inr:
            raise ValueError("FOB cannot be less than ex-factory cost")
        return self


class CostSheet(BaseModel):
    model_config = ConfigDict(frozen=True)

    sheet_id: UUID = Field(default_factory=uuid4)
    spec_id: UUID
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    raw_weight_g: float = Field(gt=0)
    finished_weight_g: float = Field(gt=0)
    yield_pct: float = Field(gt=0, le=100)

    metal_rate_used: MetalRate
    fx_used: FxSnapshot
    line_items: list[CostLineItem]
    totals: CostTotals

    # Assumptions surfaced to the user — any placeholder values, stale rates,
    # uncalibrated labor bands. Empty list means fully calibrated.
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_weights_and_totals(self) -> CostSheet:
        if self.finished_weight_g > self.raw_weight_g:
            raise ValueError(
                "finished_weight_g cannot exceed raw_weight_g "
                "(casting yield < 100%)"
            )
        # ex_factory must equal sum of all non-freight line items.
        non_freight = sum(
            li.amount_inr
            for li in self.line_items
            if li.code
            not in (LineItemCode.FREIGHT_INLAND, LineItemCode.FREIGHT_OCEAN)
        )
        if abs(non_freight - self.totals.ex_factory_inr) > 0.01:
            raise ValueError(
                f"ex_factory_inr={self.totals.ex_factory_inr} does not "
                f"match sum of non-freight line items={round(non_freight, 2)}"
            )
        return self

    def currency(self) -> Currency:
        """All line items are stored in INR by construction."""
        return Currency.INR

    def as_money_ex_factory(self) -> Money:
        return Money(value=self.totals.ex_factory_inr, currency=Currency.INR)
