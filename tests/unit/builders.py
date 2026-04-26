"""Shared fixtures for schema tests.

Builders return *valid* objects by default; tests mutate one field to create
the invalid cases. This keeps each test focused on the single invariant it
is proving, instead of hiding the change in a wall of kwargs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from mos.schemas import (
    BrassAlloy,
    CastingMethod,
    CheckResult,
    CheckRule,
    CheckStatus,
    CostLineItem,
    CostSheet,
    CostTotals,
    Currency,
    DesignSpec,
    FinishSpec,
    FxSnapshot,
    LineItemCode,
    ManufacturabilityReport,
    MaterialSpec,
    Measurement,
    MetalRate,
    Plating,
    PolishFinish,
    ProductFamily,
)


def make_material() -> MaterialSpec:
    return MaterialSpec.for_alloy(BrassAlloy.BRASS_70_30, CastingMethod.SAND)


def make_finish() -> FinishSpec:
    return FinishSpec(
        polish=PolishFinish.SATIN,
        plating=Plating.NONE,
        lacquer=True,
        patina=None,
    )


def make_design_spec(**overrides) -> DesignSpec:
    base = dict(
        brief_id=uuid4(),
        product_family=ProductFamily.CANDLE_HOLDER,
        template_id="candle_holder_classic_v1",
        dimensions={
            "base_diameter": Measurement(value=80.0, unit="mm"),
            "neck_diameter": Measurement(value=40.0, unit="mm"),
            "height": Measurement(value=120.0, unit="mm"),
            "wall_thickness": Measurement(value=3.5, unit="mm"),
        },
        material=make_material(),
        finish=make_finish(),
        motif_refs=[],
        quantity=500,
        target_unit_cost=None,
        buyer_notes="Antique finish preferred",
    )
    base.update(overrides)
    return DesignSpec(**base)


def make_manufacturability_report(spec_id=None) -> ManufacturabilityReport:
    return ManufacturabilityReport(
        spec_id=spec_id or uuid4(),
        checks=[
            CheckResult(
                rule_id=CheckRule.MIN_WALL_THICKNESS,
                status=CheckStatus.PASS,
                value=3.5,
                threshold=3.0,
                message="wall thickness 3.5mm >= 3.0mm minimum",
            ),
            CheckResult(
                rule_id=CheckRule.CLOSED_SHELL,
                status=CheckStatus.PASS,
                message="mesh is watertight",
            ),
        ],
    )


def make_metal_rate() -> MetalRate:
    return MetalRate(
        rate_per_kg_inr=720.0,
        source="manual",
        fetched_at=datetime.now(timezone.utc),
        stale=False,
    )


def make_fx() -> FxSnapshot:
    return FxSnapshot(
        inr_to_usd=0.012,
        source="manual",
        fetched_at=datetime.now(timezone.utc),
    )


def make_cost_sheet(spec_id=None) -> CostSheet:
    """Minimal valid cost sheet. Line item amounts are exact to the paisa so
    the CostSheet's internal invariants pass without rounding tolerance."""
    line_items = [
        CostLineItem(
            code=LineItemCode.RAW_BRASS,
            description="Brass 70/30, raw weight",
            qty=500.0,  # grams
            unit="g",
            unit_rate_inr=0.72,  # 720/kg
            amount_inr=360.0,
        ),
        CostLineItem(
            code=LineItemCode.CASTING_LABOR,
            description="Sand casting labor",
            qty=1.0,
            unit="piece",
            unit_rate_inr=50.0,
            amount_inr=50.0,
        ),
        CostLineItem(
            code=LineItemCode.POLISHING,
            description="Satin polish",
            qty=1.0,
            unit="piece",
            unit_rate_inr=30.0,
            amount_inr=30.0,
        ),
        CostLineItem(
            code=LineItemCode.OVERHEAD,
            description="Factory overhead allocation",
            qty=1.0,
            unit="piece",
            unit_rate_inr=40.0,
            amount_inr=40.0,
        ),
        CostLineItem(
            code=LineItemCode.MARGIN,
            description="Margin",
            qty=1.0,
            unit="piece",
            unit_rate_inr=120.0,
            amount_inr=120.0,
        ),
    ]
    ex_factory = sum(li.amount_inr for li in line_items)  # 600.0
    return CostSheet(
        spec_id=spec_id or uuid4(),
        raw_weight_g=500.0,
        finished_weight_g=450.0,
        yield_pct=90.0,
        metal_rate_used=make_metal_rate(),
        fx_used=make_fx(),
        line_items=line_items,
        totals=CostTotals(
            ex_factory_inr=ex_factory,
            fob_moradabad_inr=ex_factory,
            fob_moradabad_usd=round(ex_factory * 0.012, 2),
            cif_target_port_usd=None,
        ),
        assumptions=["labor rates from config placeholders"],
    )
