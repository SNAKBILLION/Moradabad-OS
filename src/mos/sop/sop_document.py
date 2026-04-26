"""SOP document PDF generator.

Multi-page if needed. Layout:
  Page 1 — Header (job, design summary), routing overview (numbered list of
           step titles), warnings about thin walls / undercuts from DFM
  Page 2+ — One block per step: title, instructions, tools, risks,
           estimated time

Bilingual: every `BilingualText` has an English string and a Hindi
placeholder. The `lang` parameter on the public function selects which
to display. Today only English is filled in; Hindi remains empty until
translation pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from mos.cost.engine import CostSheet
from mos.schemas import DesignSpec
from mos.sop.routing import ProcessStep, routing_for


SOP_VERSION = "0.1.0"  # bumped when template content changes


@dataclass(frozen=True)
class SopInputs:
    drawing_number: str
    cost_sheet: CostSheet | None = None  # used to pull estimated minutes


def render_sop(
    spec: DesignSpec,
    inputs: SopInputs,
    out_path: Path,
    *,
    lang: str = "en",
) -> Path:
    """Generate the SOP PDF. Returns the output path."""
    if lang not in {"en", "hi"}:
        raise ValueError(f"unsupported lang {lang!r}; expected 'en' or 'hi'")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"SOP {inputs.drawing_number}",
    )

    styles = _styles()
    flow = []
    flow += _header(spec, inputs, styles, lang)
    flow += _overview(spec, styles, lang)
    flow.append(PageBreak())
    flow += _step_blocks(spec, inputs, styles, lang)

    doc.build(flow)
    return out_path


# --- Style sheet ---------------------------------------------------------

def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontSize=18,
            spaceAfter=6 * mm, textColor=black,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontSize=13,
            spaceBefore=4 * mm, spaceAfter=2 * mm,
        ),
        "h3": ParagraphStyle(
            "h3", parent=base["Heading3"], fontSize=11,
            spaceBefore=3 * mm, spaceAfter=1 * mm,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontSize=10, leading=13,
        ),
        "label": ParagraphStyle(
            "label", parent=base["BodyText"], fontSize=9,
            textColor=HexColor("#555555"),
        ),
        "warn": ParagraphStyle(
            "warn", parent=base["BodyText"], fontSize=10,
            textColor=HexColor("#a00000"), leading=13,
        ),
    }


# --- Section builders ----------------------------------------------------

def _header(spec: DesignSpec, inputs: SopInputs, styles: dict, lang: str) -> list:
    issued = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fl = []
    fl.append(Paragraph("Standard Operating Procedure", styles["title"]))
    fl.append(Paragraph(
        f"Drawing: <b>{inputs.drawing_number}</b> &nbsp;&nbsp;&nbsp; "
        f"Issued: {issued} &nbsp;&nbsp;&nbsp; Version: {SOP_VERSION}",
        styles["label"],
    ))
    fl.append(Spacer(1, 4 * mm))
    fl.append(Paragraph("Design summary", styles["h2"]))
    summary_rows = [
        ["Product", spec.product_family.value.replace("_", " ").title()],
        ["Template", spec.template_id or "(none)"],
        ["Material", spec.material.alloy.value.replace("_", " ").upper()],
        ["Casting method", spec.material.casting_method.value],
        ["Polish", spec.finish.polish.value],
        ["Plating", spec.finish.plating.value],
        ["Lacquer", "yes" if spec.finish.lacquer else "no"],
        ["Quantity", str(spec.quantity)],
    ]
    t = Table(summary_rows, colWidths=[40 * mm, 110 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.4, black),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, black),
        ("BOX", (0, 0), (-1, -1), 0.4, black),
        ("INNERGRID", (0, 0), (-1, -1), 0.2, HexColor("#aaaaaa")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    fl.append(t)
    return fl


def _overview(spec: DesignSpec, styles: dict, lang: str) -> list:
    steps = routing_for(spec)
    fl = [Spacer(1, 6 * mm), Paragraph("Process routing", styles["h2"])]
    items = []
    for i, step in enumerate(steps, 1):
        items.append(f"{i}. {step.title.display(lang=lang)}")
    fl.append(Paragraph("<br/>".join(items), styles["body"]))

    # Warnings — surface anything notable about the design.
    warnings: list[str] = []
    if spec.material.min_wall_mm < 3.0:
        warnings.append(
            f"Minimum wall thickness is {spec.material.min_wall_mm}mm — "
            f"verify pour temperature is at the upper end of the range."
        )
    if spec.quantity > 1000:
        warnings.append(
            f"Production run of {spec.quantity} pieces — set up batch "
            f"sampling for QC inspection."
        )
    if warnings:
        fl.append(Spacer(1, 4 * mm))
        fl.append(Paragraph("Warnings", styles["h3"]))
        for w in warnings:
            fl.append(Paragraph(f"⚠ {w}", styles["warn"]))
    return fl


def _step_blocks(
    spec: DesignSpec, inputs: SopInputs, styles: dict, lang: str
) -> list:
    """One block per process step. Pulls estimated time from the cost sheet
    when a matching line item exists."""
    fl: list = [Paragraph("Process steps", styles["h2"])]
    steps = routing_for(spec)
    time_by_code = _times_from_cost_sheet(inputs.cost_sheet) if inputs.cost_sheet else {}

    for i, step in enumerate(steps, 1):
        fl.append(Spacer(1, 3 * mm))
        fl.append(Paragraph(
            f"Step {i} — {step.title.display(lang=lang)}",
            styles["h3"],
        ))
        fl.append(Paragraph(
            step.instructions.display(lang=lang),
            styles["body"],
        ))
        # Estimated time, if known
        est = time_by_code.get(step.code)
        if est is not None:
            fl.append(Paragraph(
                f"Estimated time: {est:.1f} min",
                styles["label"],
            ))
        # Tools
        if step.tools:
            tool_list = ", ".join(t.display(lang=lang) for t in step.tools)
            fl.append(Paragraph(
                f"<b>Tools:</b> {tool_list}",
                styles["body"],
            ))
        # Risks
        for risk in step.risks:
            fl.append(Paragraph(
                f"⚠ {risk.display(lang=lang)}",
                styles["warn"],
            ))
    return fl


def _times_from_cost_sheet(sheet: CostSheet) -> dict[str, float]:
    """Map process step codes to estimated minutes via cost-sheet line items.

    The cost sheet stores piece-level costs, not times, so we don't actually
    have minute estimates today. This function is a stub returning empty dict;
    when the cost engine starts emitting time estimates, this is where they
    plug in.
    """
    _ = sheet  # reserved for future time-extraction
    return {}
