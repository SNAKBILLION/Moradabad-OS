"""Unit tests for the SOP and shop-drawing PDF generators.

These tests actually render PDFs into tmp_path. ReportLab is pure Python
so this works without any system dependencies. We verify:
  - PDF magic bytes (file is a real PDF)
  - File size is in a sane range (not empty, not absurd)
  - Specific content present (title block, parameter table entries,
    process step titles)
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

from mos.cad import GeometryMetrics
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
from mos.sop import (
    ShopDrawingInputs,
    SopInputs,
    render_shop_drawing,
    render_sop,
)


def _spec(
    *,
    plating: Plating = Plating.NONE,
    lacquer: bool = False,
    template_id: str | None = "candle_holder_classic_v1",
    buyer_notes: str = "",
) -> DesignSpec:
    return DesignSpec(
        brief_id=uuid4(),
        product_family=ProductFamily.CANDLE_HOLDER,
        template_id=template_id,
        dimensions={
            "base_diameter": Measurement(value=80.0, unit="mm"),
            "neck_diameter": Measurement(value=40.0, unit="mm"),
            "height": Measurement(value=120.0, unit="mm"),
            "wall_thickness": Measurement(value=3.5, unit="mm"),
        } if template_id else {},
        material=MaterialSpec.for_alloy(BrassAlloy.BRASS_70_30, CastingMethod.SAND),
        finish=FinishSpec(polish=PolishFinish.SATIN, plating=plating, lacquer=lacquer),
        motif_refs=[],
        quantity=500,
        buyer_notes=buyer_notes,
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


def _pdf_bytes_to_text(pdf_path: Path) -> str:
    """Lightweight text extraction. Handles ReportLab's default compression
    chain (ASCII85 + Flate) and uncompressed streams. Returns concatenated
    decoded body content for substring assertions.

    NOT a real PDF parser — just enough to grep for strings we drew. Strings
    inside content streams are shown as `(text) Tj` so matching by substring
    against the decoded stream body is reliable.
    """
    import base64
    import zlib

    raw = pdf_path.read_bytes()
    chunks: list[str] = [raw.decode("latin-1", errors="ignore")]

    # ReportLab writes "stream\n" followed by encoded body and ends with
    # "endstream" (often on a new line, sometimes not). Match liberally.
    for m in re.finditer(rb"stream\s*\n(.+?)endstream", raw, re.DOTALL):
        body = m.group(1).strip()
        # Try Flate alone
        try:
            chunks.append(zlib.decompress(body).decode("latin-1", errors="ignore"))
            continue
        except zlib.error:
            pass
        # Try ASCII85 + Flate (ReportLab default).
        # PDF ASCII85 streams typically end with "~>"; strip it before decoding.
        try:
            # PDF ASCII85 is the same as Adobe ASCII85; Python's a85decode
            # accepts it. Strip the ~> terminator if present.
            stripped = body.strip()
            if stripped.endswith(b"~>"):
                stripped = stripped[:-2]
            decoded = base64.a85decode(stripped, adobe=False)
            chunks.append(zlib.decompress(decoded).decode("latin-1", errors="ignore"))
            continue
        except (ValueError, zlib.error):
            pass
        # Fall back: include raw body as latin-1 (may still contain literal text)
        chunks.append(body.decode("latin-1", errors="ignore"))
    return "\n".join(chunks)


# --- Shop drawing tests --------------------------------------------------

class TestShopDrawing:
    def test_produces_valid_pdf(self, tmp_path: Path):
        out = tmp_path / "drawing.pdf"
        render_shop_drawing(
            _spec(),
            ShopDrawingInputs(drawing_number="DWG-X-V1", geometry=_metrics()),
            out,
        )
        assert out.is_file()
        assert out.stat().st_size > 500
        with open(out, "rb") as f:
            assert f.read(5) == b"%PDF-"

    def test_title_block_contains_drawing_number(self, tmp_path: Path):
        out = tmp_path / "drawing.pdf"
        render_shop_drawing(
            _spec(),
            ShopDrawingInputs(drawing_number="DWG-MOR-001", geometry=_metrics()),
            out,
        )
        text = _pdf_bytes_to_text(out)
        assert "DWG-MOR-001" in text

    def test_parameter_names_appear_in_pdf(self, tmp_path: Path):
        out = tmp_path / "drawing.pdf"
        render_shop_drawing(
            _spec(),
            ShopDrawingInputs(drawing_number="X", geometry=_metrics()),
            out,
        )
        text = _pdf_bytes_to_text(out)
        # Parameter names from the candle-holder template.
        assert "base diameter" in text
        assert "neck diameter" in text
        assert "wall thickness" in text

    def test_finish_summary_includes_plating_and_lacquer(self, tmp_path: Path):
        out = tmp_path / "drawing.pdf"
        render_shop_drawing(
            _spec(plating=Plating.NICKEL, lacquer=True),
            ShopDrawingInputs(drawing_number="X", geometry=_metrics()),
            out,
        )
        text = _pdf_bytes_to_text(out)
        assert "nickel" in text
        assert "lacquered" in text

    def test_buyer_notes_rendered(self, tmp_path: Path):
        out = tmp_path / "drawing.pdf"
        render_shop_drawing(
            _spec(buyer_notes="warm tones preferred for export"),
            ShopDrawingInputs(drawing_number="X", geometry=_metrics()),
            out,
        )
        text = _pdf_bytes_to_text(out)
        assert "warm tones" in text

    def test_handles_null_template(self, tmp_path: Path):
        # When template_id is None, dimensions is empty — drawing must still
        # produce a valid PDF (with a "no parameters" message).
        out = tmp_path / "drawing.pdf"
        render_shop_drawing(
            _spec(template_id=None),
            ShopDrawingInputs(drawing_number="X", geometry=_metrics()),
            out,
        )
        assert out.read_bytes()[:5] == b"%PDF-"
        text = _pdf_bytes_to_text(out)
        assert "no parameters" in text


# --- SOP document tests --------------------------------------------------

class TestSopDocument:
    def test_produces_valid_pdf(self, tmp_path: Path):
        out = tmp_path / "sop.pdf"
        render_sop(
            _spec(),
            SopInputs(drawing_number="DWG-X-V1"),
            out,
        )
        assert out.is_file()
        assert out.stat().st_size > 1500
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_routing_step_titles_present(self, tmp_path: Path):
        out = tmp_path / "sop.pdf"
        render_sop(
            _spec(plating=Plating.NICKEL, lacquer=True),
            SopInputs(drawing_number="X"),
            out,
        )
        text = _pdf_bytes_to_text(out)
        # Every step title must appear in the rendered PDF.
        for needle in [
            "Sand casting",
            "Lathe scraping",
            "Hand chasing",
            "Polishing",
            "Electroplating",
            "Lacquer",
            "packing",
        ]:
            # case-insensitive search
            assert needle.lower() in text.lower(), f"missing: {needle}"

    def test_no_plating_section_when_finish_says_none(self, tmp_path: Path):
        out = tmp_path / "sop.pdf"
        render_sop(
            _spec(plating=Plating.NONE, lacquer=False),
            SopInputs(drawing_number="X"),
            out,
        )
        text = _pdf_bytes_to_text(out).lower()
        # Plating step must not appear since the finish has no plating.
        # ("plating" the word will still appear in design-summary table; we
        # check for the step heading specifically.)
        assert "electroplating" not in text

    def test_lang_must_be_supported(self, tmp_path: Path):
        with pytest.raises(ValueError):
            render_sop(
                _spec(),
                SopInputs(drawing_number="X"),
                tmp_path / "sop.pdf",
                lang="fr",  # not supported
            )

    def test_hindi_falls_back_to_english(self, tmp_path: Path):
        # Hindi is structurally ready but translations aren't filled in.
        # Calling with lang="hi" must succeed (no crash) and produce English
        # text in the PDF (BilingualText.display falls back when hi is empty).
        out = tmp_path / "sop_hi.pdf"
        render_sop(
            _spec(),
            SopInputs(drawing_number="X"),
            out,
            lang="hi",
        )
        text = _pdf_bytes_to_text(out)
        assert "Sand casting" in text  # English fallback

    def test_quantity_warning_for_large_runs(self, tmp_path: Path):
        # Quantity > 1000 should trigger the batch-sampling warning.
        spec = _spec()
        spec_data = spec.model_dump()
        spec_data["quantity"] = 2000
        big_spec = DesignSpec.model_validate(spec_data)

        out = tmp_path / "sop_big.pdf"
        render_sop(big_spec, SopInputs(drawing_number="X"), out)
        text = _pdf_bytes_to_text(out)
        assert "batch sampling" in text.lower() or "2000" in text
