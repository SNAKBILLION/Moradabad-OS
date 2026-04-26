"""Live Blender render integration test.

Runs only when Blender is actually available. Skips otherwise. The test
generates a real STL via the CAD layer, invokes the render subprocess, and
asserts a non-empty PNG of the requested dimensions came out.

Determinism: uses Eevee (raster) rather than Cycles (path-traced). Cycles
is not byte-deterministic across versions; Eevee is much closer.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from mos.cad import run_cad
from mos.render import RenderOptions, render_stl
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
from mos.templates import default_registry


def _blender_available() -> bool:
    if os.environ.get("MOS_BLENDER_BIN"):
        return Path(os.environ["MOS_BLENDER_BIN"]).is_file()
    return shutil.which("blender") is not None


pytestmark = pytest.mark.skipif(
    not _blender_available(),
    reason=(
        "Blender not available. Install Blender or set MOS_BLENDER_BIN "
        "to enable live render tests."
    ),
)


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
        material=MaterialSpec.for_alloy(
            BrassAlloy.BRASS_70_30, CastingMethod.SAND
        ),
        finish=FinishSpec(polish=PolishFinish.SATIN),
        motif_refs=[],
        quantity=100,
        buyer_notes="",
    )


class TestRenderEndToEnd:
    def test_eevee_render_produces_png(self, tmp_path: Path):
        # Build a real STL.
        cad = run_cad(_spec(), default_registry(), tmp_path / "cad")

        out_png = tmp_path / "out.png"
        # Eevee + low samples + small image keeps the test fast (< 30s).
        render_stl(
            cad.stl_path,
            out_png,
            options=RenderOptions(
                samples=8,
                seed=0,
                engine="BLENDER_EEVEE",
                width=256,
                height=256,
                timeout_seconds=120.0,
            ),
        )
        assert out_png.is_file()
        assert out_png.stat().st_size > 0
        # PNG magic bytes.
        with open(out_png, "rb") as f:
            magic = f.read(8)
        assert magic == b"\x89PNG\r\n\x1a\n"

    def test_dimensions_respected(self, tmp_path: Path):
        cad = run_cad(_spec(), default_registry(), tmp_path / "cad")
        out_png = tmp_path / "out.png"
        render_stl(
            cad.stl_path,
            out_png,
            options=RenderOptions(
                samples=4,
                engine="BLENDER_EEVEE",
                width=320,
                height=240,
                timeout_seconds=120.0,
            ),
        )
        # Verify dimensions without requiring PIL — read PNG IHDR directly.
        # IHDR is at bytes 16-23: width (4 BE), height (4 BE).
        with open(out_png, "rb") as f:
            data = f.read(24)
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        assert width == 320
        assert height == 240
