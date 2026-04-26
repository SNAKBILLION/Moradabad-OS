"""Shop drawing PDF generator.

Output is a single-page A4 datasheet:
  - Title block (top): project, drawing number, material, finish, date
  - Three views (centre): bounding-box silhouettes labelled FRONT/TOP/SIDE
    with overall dimensions. NOT full drafted projections — see M8 design
    notes. For rotationally-symmetric archetypes the silhouette is a
    meaningful representation.
  - Parameter table (bottom): every dimension from the DesignSpec
  - Finish & material notes block
  - Optional embedded render image if available

Implementation note: we use ReportLab's low-level canvas for layout because
Platypus flow models are awkward when we need to position three views in a
specific grid. The price is more arithmetic; the gain is full control over
where things land.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from mos.cad import GeometryMetrics
from mos.schemas import DesignSpec


PAGE_W, PAGE_H = A4  # 595 x 842 pt
MARGIN = 15 * mm

_TITLE_BLOCK_HEIGHT = 30 * mm
_VIEWS_HEIGHT = 90 * mm
_TABLE_HEIGHT = 60 * mm
# remaining vertical space goes to the finish/notes block


@dataclass(frozen=True)
class ShopDrawingInputs:
    """Everything the drawing needs that isn't on DesignSpec."""

    drawing_number: str  # e.g. "DWG-{spec_id_short}-V1"
    geometry: GeometryMetrics
    render_png_path: Path | None = None  # optional embedded render


def render_shop_drawing(
    spec: DesignSpec,
    inputs: ShopDrawingInputs,
    out_path: Path,
) -> Path:
    """Generate the shop drawing PDF. Returns the output path."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(out_path), pagesize=A4)

    _draw_outer_border(c)
    _draw_title_block(c, spec, inputs)
    _draw_views(c, spec, inputs)
    _draw_parameter_table(c, spec)
    _draw_notes_block(c, spec)

    c.showPage()
    c.save()
    return out_path


# --- Layout helpers ------------------------------------------------------

def _draw_outer_border(c: canvas.Canvas) -> None:
    c.setStrokeColor(black)
    c.setLineWidth(0.6)
    c.rect(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN, fill=0)


def _draw_title_block(
    c: canvas.Canvas, spec: DesignSpec, inputs: ShopDrawingInputs
) -> None:
    """Top strip with drawing number, material, finish, date, schema version."""
    top = PAGE_H - MARGIN
    bottom = top - _TITLE_BLOCK_HEIGHT
    c.setLineWidth(0.4)
    # outer
    c.rect(MARGIN, bottom, PAGE_W - 2 * MARGIN, _TITLE_BLOCK_HEIGHT, fill=0)
    # vertical separators at thirds
    inner_w = PAGE_W - 2 * MARGIN
    col1_x = MARGIN + inner_w / 3
    col2_x = MARGIN + 2 * inner_w / 3
    c.line(col1_x, bottom, col1_x, top)
    c.line(col2_x, bottom, col2_x, top)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cells = [
        ("Drawing", inputs.drawing_number),
        ("Product", spec.product_family.value.replace("_", " ").title()),
        ("Template", spec.template_id or "(none)"),
        ("Material", spec.material.alloy.value.replace("_", " ").upper()),
        ("Finish", _finish_summary(spec)),
        ("Issued", now),
    ]
    cell_w = inner_w / 3
    cell_h = _TITLE_BLOCK_HEIGHT / 2
    for i, (label, value) in enumerate(cells):
        col = i % 3
        row = i // 3  # 0 = top row, 1 = bottom row
        x = MARGIN + col * cell_w
        y_top = top - row * cell_h
        # label
        c.setFont("Helvetica", 7)
        c.setFillColor(HexColor("#666666"))
        c.drawString(x + 2 * mm, y_top - 4 * mm, label.upper())
        # value
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(black)
        c.drawString(x + 2 * mm, y_top - 9 * mm, _truncate(value, 32))


def _draw_views(
    c: canvas.Canvas, spec: DesignSpec, inputs: ShopDrawingInputs
) -> None:
    """Three labelled views in a horizontal row.

    Each view shows the bounding-box silhouette with overall dimensions.
    Front and Side are identical for rotationally-symmetric parts; Top is a
    circle of bbox_x diameter. We label them honestly.
    """
    section_top = PAGE_H - MARGIN - _TITLE_BLOCK_HEIGHT - 5 * mm
    section_bottom = section_top - _VIEWS_HEIGHT
    inner_w = PAGE_W - 2 * MARGIN

    # Three equal cells.
    cell_w = inner_w / 3
    cell_h = _VIEWS_HEIGHT
    for i in range(3):
        x = MARGIN + i * cell_w
        c.setLineWidth(0.4)
        c.rect(x, section_bottom, cell_w, cell_h, fill=0)
        if i < 2:
            c.line(x + cell_w, section_bottom, x + cell_w, section_top)

    bx = inputs.geometry.bbox_x_mm
    by = inputs.geometry.bbox_y_mm
    bz = inputs.geometry.bbox_z_mm

    _draw_silhouette_view(
        c,
        x=MARGIN,
        y=section_bottom,
        w=cell_w,
        h=cell_h,
        title="FRONT",
        width_mm=bx,
        height_mm=bz,
        is_circle=False,
    )
    _draw_silhouette_view(
        c,
        x=MARGIN + cell_w,
        y=section_bottom,
        w=cell_w,
        h=cell_h,
        title="TOP",
        width_mm=bx,
        height_mm=by,
        is_circle=True,
    )
    _draw_silhouette_view(
        c,
        x=MARGIN + 2 * cell_w,
        y=section_bottom,
        w=cell_w,
        h=cell_h,
        title="SIDE",
        width_mm=by,
        height_mm=bz,
        is_circle=False,
    )

    # Optional embedded render in a tiny inset on the front view (top-right
    # corner of cell 0).
    if inputs.render_png_path is not None and inputs.render_png_path.is_file():
        inset_size = 25 * mm
        try:
            c.drawImage(
                str(inputs.render_png_path),
                MARGIN + cell_w - inset_size - 2 * mm,
                section_top - inset_size - 2 * mm,
                width=inset_size,
                height=inset_size,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            # Render embedding is best-effort; silent skip on failure.
            pass


def _draw_silhouette_view(
    c: canvas.Canvas,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    width_mm: float,
    height_mm: float,
    is_circle: bool,
) -> None:
    """Draw a single labelled view inside the given cell."""
    # Title at top of cell
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(black)
    c.drawCentredString(x + w / 2, y + h - 6 * mm, title)

    # Drawing area (leave room for title + dimensions)
    pad = 12 * mm
    draw_w = w - 2 * pad
    draw_h = h - 2 * pad - 6 * mm  # extra for title

    # Scale the silhouette to fit; preserve aspect ratio
    if is_circle:
        # Top view: circle of diameter min(width_mm, height_mm)
        diameter_mm = min(width_mm, height_mm)
        scale = min(draw_w / diameter_mm, draw_h / diameter_mm)
        radius = (diameter_mm * scale) / 2
        cx = x + w / 2
        cy = y + pad + draw_h / 2
        c.setLineWidth(0.6)
        c.circle(cx, cy, radius, fill=0)
        # Diameter dimension below
        c.setFont("Helvetica", 8)
        c.drawCentredString(cx, y + 4 * mm, f"⌀ {width_mm:.1f} mm")
    else:
        scale = min(draw_w / width_mm, draw_h / height_mm)
        rect_w = width_mm * scale
        rect_h = height_mm * scale
        rx = x + (w - rect_w) / 2
        ry = y + pad + (draw_h - rect_h) / 2
        c.setLineWidth(0.6)
        c.rect(rx, ry, rect_w, rect_h, fill=0)
        # Width dimension below the rect
        c.setFont("Helvetica", 8)
        c.drawCentredString(rx + rect_w / 2, ry - 4 * mm, f"{width_mm:.1f} mm")
        # Height dimension to the right of the rect
        c.saveState()
        c.translate(rx + rect_w + 3 * mm, ry + rect_h / 2)
        c.rotate(90)
        c.drawCentredString(0, 0, f"{height_mm:.1f} mm")
        c.restoreState()


def _draw_parameter_table(c: canvas.Canvas, spec: DesignSpec) -> None:
    """Tabular listing of every dimension from the spec."""
    section_top = (
        PAGE_H - MARGIN - _TITLE_BLOCK_HEIGHT - 5 * mm - _VIEWS_HEIGHT - 5 * mm
    )
    section_bottom = section_top - _TABLE_HEIGHT
    inner_w = PAGE_W - 2 * MARGIN

    c.setLineWidth(0.4)
    c.rect(MARGIN, section_bottom, inner_w, _TABLE_HEIGHT, fill=0)

    # Header
    c.setFillColor(HexColor("#eeeeee"))
    c.rect(MARGIN, section_top - 7 * mm, inner_w, 7 * mm, fill=1, stroke=0)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN + 3 * mm, section_top - 5 * mm, "PARAMETERS")

    # Rows: parameter name | value (mm)
    rows = list(spec.dimensions.items())
    if not rows:
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(
            MARGIN + 3 * mm, section_top - 14 * mm,
            "(no parameters — template_id is null)",
        )
        return

    row_h = 5 * mm
    y = section_top - 7 * mm - row_h
    c.setFont("Helvetica", 9)
    col_w = inner_w / 2
    for name, measurement in rows:
        if y < section_bottom + 2 * mm:
            break  # avoid spilling out of the cell; table is fixed-size
        c.drawString(
            MARGIN + 3 * mm, y + 1 * mm,
            name.replace("_", " "),
        )
        c.drawString(
            MARGIN + col_w + 3 * mm, y + 1 * mm,
            f"{measurement.value:.2f} {measurement.unit}",
        )
        c.setLineWidth(0.2)
        c.line(MARGIN, y, MARGIN + inner_w, y)
        y -= row_h


def _draw_notes_block(c: canvas.Canvas, spec: DesignSpec) -> None:
    """Bottom block: finish, quantity, buyer notes."""
    section_top = (
        PAGE_H - MARGIN - _TITLE_BLOCK_HEIGHT - 5 * mm
        - _VIEWS_HEIGHT - 5 * mm - _TABLE_HEIGHT - 5 * mm
    )
    section_bottom = MARGIN + 5 * mm
    inner_w = PAGE_W - 2 * MARGIN
    height = section_top - section_bottom

    c.setLineWidth(0.4)
    c.rect(MARGIN, section_bottom, inner_w, height, fill=0)

    # Header
    c.setFillColor(HexColor("#eeeeee"))
    c.rect(MARGIN, section_top - 7 * mm, inner_w, 7 * mm, fill=1, stroke=0)
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN + 3 * mm, section_top - 5 * mm, "NOTES")

    y = section_top - 12 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGIN + 3 * mm, y, "Finish:")
    c.setFont("Helvetica", 9)
    c.drawString(MARGIN + 25 * mm, y, _finish_summary(spec))

    y -= 5 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(MARGIN + 3 * mm, y, "Quantity:")
    c.setFont("Helvetica", 9)
    c.drawString(MARGIN + 25 * mm, y, str(spec.quantity))

    if spec.buyer_notes:
        y -= 5 * mm
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGIN + 3 * mm, y, "Buyer notes:")
        c.setFont("Helvetica", 9)
        # Wrap manually — ReportLab canvas has no auto-wrap
        for line in _wrap(spec.buyer_notes, max_chars=80):
            y -= 4 * mm
            if y < section_bottom + 3 * mm:
                break
            c.drawString(MARGIN + 5 * mm, y, line)


# --- String helpers ------------------------------------------------------

def _finish_summary(spec: DesignSpec) -> str:
    parts = [spec.finish.polish.value]
    if spec.finish.plating.value != "none":
        parts.append(f"{spec.finish.plating.value} plated")
    if spec.finish.lacquer:
        parts.append("lacquered")
    if spec.finish.patina:
        parts.append(f"patina:{spec.finish.patina}")
    return ", ".join(parts)


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _wrap(text: str, *, max_chars: int) -> list[str]:
    """Naive word-wrap. Good enough for a notes block."""
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip()
        if len(candidate) <= max_chars:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines
