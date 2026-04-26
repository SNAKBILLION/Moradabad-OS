"""Cost engine.

Pure function: (DesignSpec, raw_weight_g, finished_weight_g, rates, metal_rate,
fx, optional freight) -> CostSheet.

The engine does not fetch anything. Callers supply the rates and weights.
This keeps the arithmetic testable without touching the network, the DB,
or CadQuery.

Formula (documented in each CostSheet.assumptions):

    material    = raw_weight_g / 1000 * metal_rate_per_kg
    casting     = raw_weight_g / 1000 * casting_rate_per_kg
    scraping    = flat
    chasing     = flat
    polishing   = flat
    plating     = flat, keyed on finish.plating; 0 if "none"
    lacquer     = flat if finish.lacquer else 0
    packing     = flat

    direct      = material + casting + scraping + chasing + polishing
                + plating + lacquer + packing
    overhead    = direct * overhead_pct / 100
    margin      = (direct + overhead) * margin_pct / 100
    ex_factory  = direct + overhead + margin
    fob_inr     = ex_factory + freight_inland (if given)
    fob_usd     = fob_inr * inr_to_usd
    cif_usd     = fob_usd + freight_ocean_usd (if given), else None

Every line item in the sheet reflects one of the terms above. Assumptions
list captures every placeholder-or-default used so downstream reviewers can
see exactly what was assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from mos.cost.rates import CostRates
from mos.schemas import (
    CostLineItem,
    CostSheet,
    CostTotals,
    DesignSpec,
    FxSnapshot,
    LineItemCode,
    MetalRate,
    Plating,
)


@dataclass(frozen=True)
class FreightInput:
    """Optional freight inputs. Inland is in INR, ocean in USD (convention:
    ocean freight is quoted and paid in USD)."""

    inland_inr: float = 0.0
    ocean_usd: float | None = None


def _round2(x: float) -> float:
    return round(x, 2)


def compute_cost_sheet(
    *,
    spec: DesignSpec,
    raw_weight_g: float,
    finished_weight_g: float,
    rates: CostRates,
    metal_rate: MetalRate,
    fx: FxSnapshot,
    freight: FreightInput | None = None,
) -> CostSheet:
    """Produce a CostSheet for a single unit of the given spec.

    raw_weight_g is the metal POURED (including gates, sprues, and scrap
    that will be recycled). finished_weight_g is the final part mass.
    The engine does not enforce raw >= finished here — CostSheet's own
    validator does.
    """
    if raw_weight_g <= 0:
        raise ValueError("raw_weight_g must be > 0")
    if finished_weight_g <= 0:
        raise ValueError("finished_weight_g must be > 0")

    if metal_rate.stale:
        stale_note = (
            f"metal rate is STALE (source={metal_rate.source}, fetched="
            f"{metal_rate.fetched_at.isoformat()})"
        )
    else:
        stale_note = None

    yield_pct = finished_weight_g / raw_weight_g * 100.0

    # --- Line items ----------------------------------------------------
    #
    # RAW_BRASS and CASTING_LABOR are quoted per kg in the industry; we store
    # them that way so qty * unit_rate works out without per-gram rounding
    # loss. (qty in g with unit_rate rounded to 2 decimals breaks the
    # CostLineItem invariant for rates like 725 INR/kg.)

    raw_kg = round(raw_weight_g / 1000.0, 6)

    material = CostLineItem(
        code=LineItemCode.RAW_BRASS,
        description=f"{spec.material.alloy.value}, raw weight",
        qty=raw_kg,
        unit="kg",
        unit_rate_inr=metal_rate.rate_per_kg_inr,
        amount_inr=_round2(raw_kg * metal_rate.rate_per_kg_inr),
    )

    casting = CostLineItem(
        code=LineItemCode.CASTING_LABOR,
        description="Sand casting labor (₹/kg raw)",
        qty=raw_kg,
        unit="kg",
        unit_rate_inr=rates.labor.casting_per_kg_raw_inr,
        amount_inr=_round2(raw_kg * rates.labor.casting_per_kg_raw_inr),
    )

    scraping = CostLineItem(
        code=LineItemCode.SCRAPING_LABOR,
        description="Lathe scraping / deburring",
        qty=1.0,
        unit="piece",
        unit_rate_inr=rates.labor.scraping_per_piece_inr,
        amount_inr=rates.labor.scraping_per_piece_inr,
    )

    chasing = CostLineItem(
        code=LineItemCode.CHASING_LABOR,
        description="Hand chasing / finishing",
        qty=1.0,
        unit="piece",
        unit_rate_inr=rates.labor.chasing_per_piece_inr,
        amount_inr=rates.labor.chasing_per_piece_inr,
    )

    polishing = CostLineItem(
        code=LineItemCode.POLISHING,
        description=f"{spec.finish.polish.value} polish",
        qty=1.0,
        unit="piece",
        unit_rate_inr=rates.labor.polishing_per_piece_inr,
        amount_inr=rates.labor.polishing_per_piece_inr,
    )

    line_items: list[CostLineItem] = [
        material, casting, scraping, chasing, polishing,
    ]

    # Plating — included only when finish.plating != NONE.
    if spec.finish.plating != Plating.NONE:
        plating_rate = rates.finishing.plating.rate_for(
            spec.finish.plating.value
        )
        line_items.append(
            CostLineItem(
                code=LineItemCode.PLATING,
                description=f"{spec.finish.plating.value} plating",
                qty=1.0,
                unit="piece",
                unit_rate_inr=plating_rate,
                amount_inr=plating_rate,
            )
        )

    # Lacquer — included only when requested.
    if spec.finish.lacquer:
        line_items.append(
            CostLineItem(
                code=LineItemCode.LACQUER,
                description="Lacquer coat",
                qty=1.0,
                unit="piece",
                unit_rate_inr=rates.finishing.lacquer_per_piece_inr,
                amount_inr=rates.finishing.lacquer_per_piece_inr,
            )
        )

    line_items.append(
        CostLineItem(
            code=LineItemCode.PACKING,
            description="Inner + master carton packing",
            qty=1.0,
            unit="piece",
            unit_rate_inr=rates.packing_per_piece_inr,
            amount_inr=rates.packing_per_piece_inr,
        )
    )

    # --- Overhead, margin, totals --------------------------------------

    direct = sum(li.amount_inr for li in line_items)
    overhead_amount = _round2(direct * rates.overhead_pct / 100.0)
    line_items.append(
        CostLineItem(
            code=LineItemCode.OVERHEAD,
            description=f"Overhead ({rates.overhead_pct}% of direct)",
            qty=1.0,
            unit="piece",
            unit_rate_inr=overhead_amount,
            amount_inr=overhead_amount,
        )
    )

    margin_base = direct + overhead_amount
    margin_amount = _round2(margin_base * rates.margin_pct / 100.0)
    line_items.append(
        CostLineItem(
            code=LineItemCode.MARGIN,
            description=f"Margin ({rates.margin_pct}% of direct+overhead)",
            qty=1.0,
            unit="piece",
            unit_rate_inr=margin_amount,
            amount_inr=margin_amount,
        )
    )

    ex_factory = _round2(
        sum(li.amount_inr for li in line_items)
    )

    # Freight (optional) and FOB/CIF ------------------------------------

    inland = 0.0
    ocean_usd: float | None = None
    if freight is not None:
        if freight.inland_inr < 0:
            raise ValueError("inland_inr cannot be negative")
        if freight.ocean_usd is not None and freight.ocean_usd < 0:
            raise ValueError("ocean_usd cannot be negative")
        inland = freight.inland_inr
        ocean_usd = freight.ocean_usd
        if inland > 0:
            line_items.append(
                CostLineItem(
                    code=LineItemCode.FREIGHT_INLAND,
                    description="Inland freight (Moradabad to port)",
                    qty=1.0,
                    unit="lot",
                    unit_rate_inr=inland,
                    amount_inr=inland,
                )
            )

    fob_inr = _round2(ex_factory + inland)
    fob_usd = _round2(fob_inr * fx.inr_to_usd)
    cif_usd: float | None
    if ocean_usd is not None:
        cif_usd = _round2(fob_usd + ocean_usd)
        # Record ocean freight as a line item so the sheet is self-describing.
        # Stored in INR via the reverse-fx for consistency with other items.
        ocean_inr = _round2(ocean_usd / fx.inr_to_usd)
        line_items.append(
            CostLineItem(
                code=LineItemCode.FREIGHT_OCEAN,
                description="Ocean freight (USD converted for bookkeeping)",
                qty=1.0,
                unit="lot",
                unit_rate_inr=ocean_inr,
                amount_inr=ocean_inr,
            )
        )
    else:
        cif_usd = None

    totals = CostTotals(
        ex_factory_inr=ex_factory,
        fob_moradabad_inr=fob_inr,
        fob_moradabad_usd=fob_usd,
        cif_target_port_usd=cif_usd,
    )

    # --- Assumptions surfaced to the reviewer --------------------------

    assumptions: list[str] = [
        f"cost rates version {rates.version} ({rates.content_hash})",
        (
            f"overhead {rates.overhead_pct}% of direct; "
            f"margin {rates.margin_pct}% of (direct+overhead)"
        ),
        f"casting labor applied to raw weight; other labor flat per piece",
    ]
    if rates.version.endswith("-placeholder"):
        assumptions.append(
            "labor/overhead/margin rates are PLACEHOLDERS — not factory-calibrated"
        )
    if stale_note is not None:
        assumptions.append(stale_note)
    if freight is None:
        assumptions.append("no freight included; ex-factory == FOB Moradabad")

    return CostSheet(
        spec_id=spec.spec_id,
        raw_weight_g=raw_weight_g,
        finished_weight_g=finished_weight_g,
        yield_pct=round(yield_pct, 4),
        metal_rate_used=metal_rate,
        fx_used=fx,
        line_items=line_items,
        totals=totals,
        assumptions=assumptions,
    )
