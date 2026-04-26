"""Tests for common value objects and MaterialSpec derivation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mos.schemas import (
    BrassAlloy,
    CastingMethod,
    Currency,
    MaterialSpec,
    Measurement,
    Money,
    Plating,
    PolishFinish,
)
from mos.schemas.design_spec import FinishSpec


class TestMeasurement:
    def test_valid_mm(self):
        m = Measurement(value=10.0, unit="mm")
        assert m.value == 10.0
        assert m.unit == "mm"

    def test_zero_rejected(self):
        with pytest.raises(ValidationError):
            Measurement(value=0.0, unit="mm")

    def test_negative_rejected(self):
        with pytest.raises(ValidationError):
            Measurement(value=-5.0, unit="mm")

    def test_unsupported_unit_rejected(self):
        with pytest.raises(ValidationError):
            Measurement(value=10.0, unit="inches")


class TestMoney:
    def test_rounds_to_paisa(self):
        m = Money(value=123.456789, currency=Currency.INR)
        assert m.value == 123.46

    def test_negative_rejected(self):
        with pytest.raises(ValidationError):
            Money(value=-1.0, currency=Currency.INR)

    def test_zero_allowed(self):
        Money(value=0.0, currency=Currency.USD)


class TestMaterialSpec:
    def test_helper_produces_valid_spec(self):
        m = MaterialSpec.for_alloy(BrassAlloy.BRASS_70_30)
        assert m.density_g_cm3 == 8.53
        assert m.min_wall_mm == 3.0
        assert m.casting_method == CastingMethod.SAND

    def test_wrong_density_rejected(self):
        with pytest.raises(ValidationError):
            MaterialSpec(
                alloy=BrassAlloy.BRASS_70_30,
                casting_method=CastingMethod.SAND,
                density_g_cm3=9.99,  # wrong
                min_wall_mm=3.0,
            )

    def test_wrong_min_wall_rejected(self):
        with pytest.raises(ValidationError):
            MaterialSpec(
                alloy=BrassAlloy.BRASS_70_30,
                casting_method=CastingMethod.SAND,
                density_g_cm3=8.53,
                min_wall_mm=1.0,  # wrong
            )

    def test_lost_wax_not_yet_supported_via_helper(self):
        with pytest.raises(NotImplementedError):
            MaterialSpec.for_alloy(
                BrassAlloy.BRASS_70_30, CastingMethod.LOST_WAX
            )


class TestFinishSpec:
    def test_minimal(self):
        f = FinishSpec(polish=PolishFinish.MIRROR)
        assert f.plating == Plating.NONE
        assert f.lacquer is False

    def test_long_patina_rejected(self):
        with pytest.raises(ValidationError):
            FinishSpec(polish=PolishFinish.ANTIQUE, patina="x" * 100)
