"""Tests for CostSheet — line-item arithmetic, yield check, ex-factory totals.

This contract is the most arithmetic-heavy in the system; it is also the
contract where mistakes are most visible to the factory owner. Hence the
density of tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from mos.schemas import (
    CostLineItem,
    CostSheet,
    CostTotals,
    LineItemCode,
)

from .builders import make_cost_sheet, make_fx, make_metal_rate


class TestCostLineItem:
    def test_amount_matches_qty_rate(self):
        CostLineItem(
            code=LineItemCode.RAW_BRASS,
            description="Brass",
            qty=100.0,
            unit="g",
            unit_rate_inr=0.72,
            amount_inr=72.0,
        )

    def test_amount_mismatch_rejected(self):
        with pytest.raises(ValidationError, match="does not match"):
            CostLineItem(
                code=LineItemCode.RAW_BRASS,
                description="Brass",
                qty=100.0,
                unit="g",
                unit_rate_inr=0.72,
                amount_inr=999.0,  # wrong
            )

    def test_paisa_tolerance_allowed(self):
        # 100 * 0.333 = 33.3 exactly; caller rounded to 33.30. Within 0.01.
        CostLineItem(
            code=LineItemCode.POLISHING,
            description="rounding test",
            qty=100.0,
            unit="min",
            unit_rate_inr=0.333,
            amount_inr=33.30,
        )


class TestCostSheetInvariants:
    def test_valid_sheet_builds(self):
        s = make_cost_sheet()
        assert s.totals.ex_factory_inr == 600.0
        assert s.currency().value == "INR"

    def test_finished_cannot_exceed_raw_weight(self):
        s = make_cost_sheet()
        data = s.model_dump()
        data["raw_weight_g"] = 100.0
        data["finished_weight_g"] = 200.0
        with pytest.raises(ValidationError, match="cannot exceed"):
            CostSheet.model_validate(data)

    def test_ex_factory_must_match_sum_of_non_freight_items(self):
        s = make_cost_sheet()
        data = s.model_dump()
        # Line items sum to 600. Set ex_factory below that so the non-freight
        # match fails, but keep fob >= ex_factory so we don't trip the FOB
        # invariant first.
        data["totals"]["ex_factory_inr"] = 500.0
        with pytest.raises(ValidationError, match="does not match"):
            CostSheet.model_validate(data)

    def test_freight_does_not_count_toward_exfactory(self):
        """Freight line items must be excluded from the ex-factory total —
        this is a real bug we could easily introduce later."""
        base = make_cost_sheet()
        freight_item = CostLineItem(
            code=LineItemCode.FREIGHT_OCEAN,
            description="Mumbai to Rotterdam",
            qty=1.0,
            unit="lot",
            unit_rate_inr=5000.0,
            amount_inr=5000.0,
        )
        data = base.model_dump()
        data["line_items"].append(freight_item.model_dump())
        # totals.ex_factory_inr unchanged — should still validate because
        # freight is excluded from the invariant.
        CostSheet.model_validate(data)

    def test_fob_below_exfactory_rejected(self):
        data = make_cost_sheet().model_dump()
        data["totals"]["fob_moradabad_inr"] = 100.0  # < ex_factory 600
        with pytest.raises(ValidationError, match="FOB cannot be less"):
            CostSheet.model_validate(data)


class TestCostSheetMetadata:
    def test_metal_rate_stale_flag_carries(self):
        r = make_metal_rate()
        data = r.model_dump()
        data["stale"] = True
        # Can't mutate frozen; rebuild from dict.
        from mos.schemas import MetalRate

        r2 = MetalRate.model_validate(data)
        assert r2.stale is True

    def test_fx_positive_rate_required(self):
        from datetime import datetime, timezone

        from mos.schemas import FxSnapshot

        # Constructing directly with zero rate must fail — model_copy does not
        # re-validate in pydantic v2, so use the constructor path.
        with pytest.raises(ValidationError):
            FxSnapshot(
                inr_to_usd=0.0,
                source="test",
                fetched_at=datetime.now(timezone.utc),
            )
