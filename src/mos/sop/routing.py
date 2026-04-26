"""Manufacturing process routing for brass sand casting.

A *routing* is the ordered sequence of process steps to make a part. Every
step has tools, an estimated time, risk callouts, and a free-text instruction.

This routing is generic — appropriate for the bulk of rotationally-symmetric
brass sand-cast products. Factory-specific overrides will arrive via the
feedback loop (M11a) and will eventually replace this default per-template
or per-factory. For now: one routing fits all archetypes.

Bilingual structure: every user-visible string has an English value (`en`)
and a Hindi placeholder (`hi`). Translation pass replaces the empty Hindi
strings; no code changes needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mos.schemas import DesignSpec, Plating


@dataclass(frozen=True)
class BilingualText:
    en: str
    hi: str = ""  # filled by translation pass; empty string is the marker

    def display(self, *, lang: str = "en") -> str:
        if lang == "hi" and self.hi:
            return self.hi
        return self.en


@dataclass(frozen=True)
class ProcessStep:
    code: str  # stable identifier for cross-referencing (e.g. "CASTING")
    title: BilingualText
    instructions: BilingualText
    tools: tuple[BilingualText, ...]
    risks: tuple[BilingualText, ...] = ()
    estimated_minutes: float | None = None  # filled from cost sheet when known


def _t(en: str) -> BilingualText:
    return BilingualText(en=en)


# --- Generic step library ------------------------------------------------

CASTING = ProcessStep(
    code="CASTING",
    title=_t("Sand casting"),
    instructions=_t(
        "Pack moulding sand around the master pattern. Form the cope and "
        "drag halves with a parting line at the equator. Cut runners and "
        "risers. Pour molten brass at 1000-1050°C. Allow to cool fully "
        "before breaking the mould. Knock off gates and runners with a "
        "hammer; trim flash with a hand chisel."
    ),
    tools=(
        _t("Moulding flask"),
        _t("Moulding sand (green)"),
        _t("Crucible furnace"),
        _t("Pouring ladle"),
        _t("Hand chisel"),
        _t("Hammer"),
    ),
    risks=(
        _t("Molten brass at >1000°C — wear leather apron and face shield."),
        _t("Pour too cold and the metal will not fill thin sections."),
        _t("Insufficient venting traps gas, producing porosity in the wall."),
    ),
)

SCRAPING = ProcessStep(
    code="SCRAPING",
    title=_t("Lathe scraping and deburring"),
    instructions=_t(
        "Mount the cast piece on the lathe. Scrape the outer surface to "
        "remove sand inclusions and parting-line flash. File any burrs at "
        "rim and base. Verify outer dimensions against the parameter table."
    ),
    tools=(
        _t("Lathe"),
        _t("Hand scrapers"),
        _t("Files (flat and half-round)"),
        _t("Calipers"),
    ),
    risks=(
        _t("Excessive scraping reduces wall thickness — measure frequently."),
    ),
)

CHASING = ProcessStep(
    code="CHASING",
    title=_t("Hand chasing"),
    instructions=_t(
        "Apply ornamental detail using chasing punches and a chasing "
        "hammer. For motif regions specified in the design, follow the "
        "reference drawing. Work from the centre of each motif outward to "
        "avoid distorting adjacent areas."
    ),
    tools=(
        _t("Chasing hammer"),
        _t("Chasing punches (assorted)"),
        _t("Bench pitch / chasing block"),
    ),
    risks=(
        _t("Striking too hard cracks the wall on thin-section parts."),
    ),
)

POLISHING = ProcessStep(
    code="POLISHING",
    title=_t("Polishing"),
    instructions=_t(
        "Polish to the specified finish using progressively finer abrasive "
        "wheels. Mirror finish requires final buffing with rouge compound. "
        "Satin finish stops at 400-grit fibre wheel. Antique finish is "
        "applied AFTER chemical patination, not here."
    ),
    tools=(
        _t("Polishing lathe"),
        _t("Sisal and cloth wheels"),
        _t("Tripoli compound"),
        _t("Rouge compound"),
    ),
    risks=(
        _t("Friction heat anneals the surface — keep moving, don't dwell."),
    ),
)

PLATING = ProcessStep(
    code="PLATING",
    title=_t("Electroplating"),
    instructions=_t(
        "Clean and degrease the polished surface in alkaline bath. Plate "
        "to the specified plating type and thickness. Rinse in deionised "
        "water and dry."
    ),
    tools=(
        _t("Plating tank"),
        _t("Rectifier"),
        _t("Cleaning bath chemicals"),
    ),
    risks=(
        _t("Plating bath chemicals are corrosive — wear gloves and goggles."),
        _t("Insufficient cleaning produces patchy adhesion."),
    ),
)

LACQUER = ProcessStep(
    code="LACQUER",
    title=_t("Lacquer coat"),
    instructions=_t(
        "Apply a clear lacquer coat to prevent oxidation. Spray in a "
        "ventilated area; allow 4 hours to fully cure before packing."
    ),
    tools=(
        _t("Spray gun"),
        _t("Clear acrylic lacquer"),
        _t("Drying rack"),
    ),
    risks=(
        _t("Solvent fumes — ventilate the work area."),
        _t("Packing before fully cured leaves fingerprints in the lacquer."),
    ),
)

PACKING = ProcessStep(
    code="PACKING",
    title=_t("Inspection and packing"),
    instructions=_t(
        "Inspect each piece against the parameter table and finish "
        "specification. Wrap in tissue paper, place in inner carton, "
        "then load into export master carton with cushioning."
    ),
    tools=(
        _t("Inspection lamp"),
        _t("Calipers"),
        _t("Tissue paper"),
        _t("Inner cartons"),
        _t("Master export cartons"),
    ),
    risks=(
        _t("Skipped inspection at this stage means defects ship to buyer."),
    ),
)


def routing_for(spec: DesignSpec) -> tuple[ProcessStep, ...]:
    """Build the ordered routing for a DesignSpec.

    Plating and lacquer are conditional on the finish spec. Everything else
    is mandatory for sand-cast brass.
    """
    steps: list[ProcessStep] = [CASTING, SCRAPING, CHASING, POLISHING]
    if spec.finish.plating != Plating.NONE:
        steps.append(PLATING)
    if spec.finish.lacquer:
        steps.append(LACQUER)
    steps.append(PACKING)
    return tuple(steps)
