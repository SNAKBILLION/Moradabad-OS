"""Tests for the Template protocol and param validation.

Uses an inline minimal template so tests don't depend on the production
CandleHolderClassic geometry. The CandleHolderClassic template is exercised
by integration-level tests in test_cad_runner.py.
"""

from __future__ import annotations

import cadquery as cq
import pytest

from mos.templates import (
    ParamSpec,
    Template,
    TemplateParamError,
    template_metadata,
    validate_params,
)


class _MinimalTemplate:
    """Simplest thing that satisfies the Template protocol."""

    template_id = "_test_minimal_v1"
    version = "0.0.1"
    product_family = "test"
    description = "test fixture"
    param_schema = (
        ParamSpec(name="d", description="diameter", min_mm=10.0, max_mm=100.0),
        ParamSpec(name="h", description="height", min_mm=5.0, max_mm=50.0),
    )
    regions = ("body",)
    declared_min_wall_mm = 3.0
    declared_min_draft_deg = 2.0
    declared_produces_no_undercuts = True

    def build(self, params: dict[str, float]) -> cq.Workplane:
        return cq.Workplane("XY").circle(params["d"] / 2).extrude(params["h"])


class TestProtocolConformance:
    def test_minimal_template_matches_protocol(self):
        t = _MinimalTemplate()
        # runtime_checkable Protocol — isinstance reflects whether the
        # structural contract holds.
        assert isinstance(t, Template)


class TestValidateParams:
    def test_happy_path(self):
        t = _MinimalTemplate()
        validate_params(t, {"d": 30.0, "h": 20.0})  # must not raise

    def test_missing_param_rejected(self):
        t = _MinimalTemplate()
        with pytest.raises(TemplateParamError, match="missing params"):
            validate_params(t, {"d": 30.0})

    def test_extra_param_rejected(self):
        t = _MinimalTemplate()
        with pytest.raises(TemplateParamError, match="unexpected params"):
            validate_params(t, {"d": 30.0, "h": 20.0, "extra": 5.0})

    def test_below_range_rejected(self):
        t = _MinimalTemplate()
        with pytest.raises(TemplateParamError, match="outside declared range"):
            validate_params(t, {"d": 5.0, "h": 20.0})  # d < 10 min

    def test_above_range_rejected(self):
        t = _MinimalTemplate()
        with pytest.raises(TemplateParamError, match="outside declared range"):
            validate_params(t, {"d": 30.0, "h": 500.0})  # h > 50 max

    def test_inclusive_bounds(self):
        t = _MinimalTemplate()
        # Both boundaries must be accepted.
        validate_params(t, {"d": 10.0, "h": 5.0})
        validate_params(t, {"d": 100.0, "h": 50.0})


class TestTemplateMetadata:
    def test_metadata_is_json_serializable(self):
        import json

        t = _MinimalTemplate()
        meta = template_metadata(t)
        # Must be cleanly JSON-serializable for storage in PipelineSnapshot.
        as_json = json.dumps(meta)
        assert "_test_minimal_v1" in as_json

    def test_metadata_captures_declarations(self):
        t = _MinimalTemplate()
        meta = template_metadata(t)
        assert meta["declared_min_wall_mm"] == 3.0
        assert meta["declared_min_draft_deg"] == 2.0
        assert meta["declared_produces_no_undercuts"] is True
        assert len(meta["param_schema"]) == 2
