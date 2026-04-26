"""Shop drawing + SOP PDF generators.

Two public functions:
  - render_shop_drawing(spec, inputs, out_path) -> Path
  - render_sop(spec, inputs, out_path, lang="en") -> Path

Both produce single-file PDFs at the given path. Bilingual structure is in
place (every user-visible string is a BilingualText with English filled in
and Hindi reserved); a translation pass replaces the empty Hindi values.
"""

from __future__ import annotations

from .routing import (
    BilingualText,
    ProcessStep,
    routing_for,
)
from .shop_drawing import ShopDrawingInputs, render_shop_drawing
from .sop_document import SOP_VERSION, SopInputs, render_sop

__all__ = [
    "BilingualText",
    "ProcessStep",
    "SOP_VERSION",
    "ShopDrawingInputs",
    "SopInputs",
    "render_shop_drawing",
    "render_sop",
    "routing_for",
]
