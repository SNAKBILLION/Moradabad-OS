"""Tests for DesignSpec — schema_version pinning, template_id/dimensions
interaction, and round-trip JSON serialization."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from mos.schemas import SCHEMA_VERSION, DesignSpec, ProductFamily
from mos.schemas.design_spec import FinishSpec, MaterialSpec

from .builders import make_design_spec, make_finish, make_material


class TestDesignSpecValid:
    def test_builder_returns_valid(self):
        spec = make_design_spec()
        assert spec.schema_version == SCHEMA_VERSION
        assert spec.product_family == ProductFamily.CANDLE_HOLDER
        assert spec.template_id == "candle_holder_classic_v1"
        assert len(spec.dimensions) == 4
        assert spec.quantity == 500

    def test_null_template_and_empty_dimensions_ok(self):
        # LLM-couldn't-match state: must allow None template + no dimensions.
        spec = make_design_spec(template_id=None, dimensions={})
        assert spec.template_id is None
        assert spec.dimensions == {}


class TestDesignSpecInvariants:
    def test_null_template_with_dimensions_rejected(self):
        # The confusing middle state we explicitly outlawed.
        with pytest.raises(ValidationError, match="dimensions must be empty"):
            make_design_spec(template_id=None)

    def test_wrong_schema_version_rejected(self):
        with pytest.raises(ValidationError, match="Unsupported schema_version"):
            DesignSpec(
                schema_version="0.9",
                brief_id=uuid4(),
                product_family=ProductFamily.BOWL,
                template_id=None,
                dimensions={},
                material=make_material(),
                finish=make_finish(),
                quantity=1,
            )

    def test_quantity_zero_rejected(self):
        with pytest.raises(ValidationError):
            make_design_spec(quantity=0)

    def test_quantity_absurdly_high_rejected(self):
        with pytest.raises(ValidationError):
            make_design_spec(quantity=1_000_000)

    def test_buyer_notes_too_long_rejected(self):
        with pytest.raises(ValidationError):
            make_design_spec(buyer_notes="x" * 5000)


class TestDesignSpecRoundTrip:
    def test_json_round_trip_preserves_equality(self):
        original = make_design_spec()
        as_json = original.model_dump_json()
        # Ensure it's valid JSON
        parsed = json.loads(as_json)
        assert parsed["schema_version"] == SCHEMA_VERSION
        # Rebuild and compare
        rebuilt = DesignSpec.model_validate_json(as_json)
        assert rebuilt == original

    def test_frozen_model_cannot_be_mutated(self):
        spec = make_design_spec()
        with pytest.raises(ValidationError):
            # pydantic v2 raises ValidationError on frozen assignment
            spec.quantity = 999  # type: ignore[misc]
