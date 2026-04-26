"""Unit tests for the SOP routing builder."""

from __future__ import annotations

from uuid import uuid4

import pytest

from mos.schemas import (
    BrassAlloy,
    CastingMethod,
    DesignSpec,
    FinishSpec,
    MaterialSpec,
    Measurement,
    Plating,
    PolishFinish,
    ProductFamily,
)
from mos.sop import BilingualText, routing_for


def _spec(*, plating: Plating = Plating.NONE, lacquer: bool = False) -> DesignSpec:
    return DesignSpec(
        brief_id=uuid4(),
        product_family=ProductFamily.CANDLE_HOLDER,
        template_id="candle_holder_classic_v1",
        dimensions={"base_diameter": Measurement(value=80.0, unit="mm"),
                    "neck_diameter": Measurement(value=40.0, unit="mm"),
                    "height": Measurement(value=120.0, unit="mm"),
                    "wall_thickness": Measurement(value=3.5, unit="mm")},
        material=MaterialSpec.for_alloy(BrassAlloy.BRASS_70_30, CastingMethod.SAND),
        finish=FinishSpec(polish=PolishFinish.SATIN, plating=plating, lacquer=lacquer),
        motif_refs=[], quantity=10, buyer_notes="",
    )


class TestRoutingFor:
    def test_minimal_routing_no_plating_no_lacquer(self):
        steps = routing_for(_spec())
        codes = [s.code for s in steps]
        # Casting always first, packing always last; no plating or lacquer.
        assert codes == ["CASTING", "SCRAPING", "CHASING", "POLISHING", "PACKING"]

    def test_plating_added_when_specified(self):
        steps = routing_for(_spec(plating=Plating.NICKEL))
        codes = [s.code for s in steps]
        assert "PLATING" in codes
        assert codes.index("PLATING") < codes.index("PACKING")
        # Plating must come AFTER polishing (you plate the polished surface)
        assert codes.index("POLISHING") < codes.index("PLATING")

    def test_lacquer_added_when_requested(self):
        steps = routing_for(_spec(lacquer=True))
        codes = [s.code for s in steps]
        assert "LACQUER" in codes
        # Lacquer is the last finishing step before packing
        assert codes.index("LACQUER") < codes.index("PACKING")

    def test_full_routing_plating_then_lacquer(self):
        steps = routing_for(_spec(plating=Plating.SILVER, lacquer=True))
        codes = [s.code for s in steps]
        assert codes.index("PLATING") < codes.index("LACQUER")


class TestBilingualText:
    def test_english_default(self):
        t = BilingualText(en="Polish")
        assert t.display() == "Polish"
        # No Hindi yet — falls back to English.
        assert t.display(lang="hi") == "Polish"

    def test_hindi_when_set(self):
        t = BilingualText(en="Polish", hi="पॉलिश")
        assert t.display(lang="en") == "Polish"
        assert t.display(lang="hi") == "पॉलिश"

    def test_empty_hindi_falls_back_to_english(self):
        # The marker for "not yet translated" — empty string falls back.
        t = BilingualText(en="Casting", hi="")
        assert t.display(lang="hi") == "Casting"


class TestStepContent:
    def test_every_step_has_non_empty_english(self):
        for step in routing_for(_spec(plating=Plating.GOLD, lacquer=True)):
            assert step.title.en
            assert step.instructions.en
            assert step.code

    def test_every_step_has_at_least_one_tool(self):
        for step in routing_for(_spec(plating=Plating.GOLD, lacquer=True)):
            assert len(step.tools) >= 1
            for tool in step.tools:
                assert tool.en
