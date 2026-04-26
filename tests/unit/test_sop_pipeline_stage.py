"""Tests for the SOP stage's non-fatal contract.

PDF generation must not fail a job. If render_shop_drawing or render_sop
raises, the stage marks itself SKIPPED with a reason. This mirrors the
contract for the render stage.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock
from uuid import uuid4

from mos.cad import GeometryMetrics
from mos.schemas import (
    ArtifactBundle,
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
from mos.storage import InMemoryObjectStore
from mos.worker.pipeline import _stage_sop


def _spec() -> DesignSpec:
    return DesignSpec(
        brief_id=uuid4(),
        product_family=ProductFamily.CANDLE_HOLDER,
        template_id="candle_holder_classic_v1",
        dimensions={
            "base_diameter": Measurement(value=80.0, unit="mm"),
            "neck_diameter": Measurement(value=40.0, unit="mm"),
            "height": Measurement(value=120.0, unit="mm"),
            "wall_thickness": Measurement(value=3.5, unit="mm"),
        },
        material=MaterialSpec.for_alloy(BrassAlloy.BRASS_70_30, CastingMethod.SAND),
        finish=FinishSpec(polish=PolishFinish.SATIN),
        motif_refs=[],
        quantity=10,
        buyer_notes="",
    )


def _metrics() -> GeometryMetrics:
    return GeometryMetrics(
        volume_mm3=97000.0,
        mass_g=828.0,
        bbox_x_mm=80.0,
        bbox_y_mm=80.0,
        bbox_z_mm=120.0,
        stl_is_watertight=True,
    )


class TestStageSopSuccess:
    def test_uploads_both_pdfs(self):
        store = InMemoryObjectStore()
        out, reason = _stage_sop(
            _spec(),
            uuid4(),
            cost_sheet=None,
            geometry=_metrics(),
            bundle=ArtifactBundle(),
            store=store,
        )
        assert reason is None
        assert out.shop_drawing_pdf_uri is not None
        assert out.sop_pdf_uri is not None
        # Both URIs are retrievable.
        drawing_bytes = store.get_bytes(out.shop_drawing_pdf_uri)
        sop_bytes = store.get_bytes(out.sop_pdf_uri)
        assert drawing_bytes[:5] == b"%PDF-"
        assert sop_bytes[:5] == b"%PDF-"


class TestStageSopFailure:
    def test_pdf_error_returns_skip_reason(self):
        store = InMemoryObjectStore()
        with mock.patch(
            "mos.sop.render_shop_drawing",
            side_effect=RuntimeError("disk full"),
        ):
            out, reason = _stage_sop(
                _spec(),
                uuid4(),
                cost_sheet=None,
                geometry=_metrics(),
                bundle=ArtifactBundle(),
                store=store,
            )
        assert reason is not None
        assert "PDF generation failed" in reason
        assert "RuntimeError" in reason
        assert out.shop_drawing_pdf_uri is None
        assert out.sop_pdf_uri is None
