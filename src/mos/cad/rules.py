"""Load DFM rules from config/dfm_rules.yaml.

The rules are kept in YAML (not code) because factory calibration updates
them frequently. The `version` string is recorded in every PipelineSnapshot
so we can reproduce a job's DFM outcome exactly given its snapshot.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SandCastingRules:
    min_wall_mm: float
    min_draft_deg: float
    max_bbox_x_mm: float
    max_bbox_y_mm: float
    max_bbox_z_mm: float
    max_mass_g: float
    shrinkage_linear: float


@dataclass(frozen=True)
class DfmRules:
    version: str
    content_hash: str  # sha256 of the file content, used for snapshot reproducibility
    brass_sand: SandCastingRules


def _default_rules_path() -> Path:
    # config/ sits at repo root, alongside src/.
    return Path(__file__).resolve().parents[3] / "config" / "dfm_rules.yaml"


def load_dfm_rules(path: Path | None = None) -> DfmRules:
    p = path or _default_rules_path()
    raw = p.read_bytes()
    content_hash = "sha256:" + hashlib.sha256(raw).hexdigest()[:16]
    data = yaml.safe_load(raw)

    brass = data["sand_casting"]["brass"]
    bbox = brass["max_bounding_box_mm"]
    return DfmRules(
        version=data["version"],
        content_hash=content_hash,
        brass_sand=SandCastingRules(
            min_wall_mm=float(brass["min_wall_mm"]),
            min_draft_deg=float(brass["min_draft_deg"]),
            max_bbox_x_mm=float(bbox["x"]),
            max_bbox_y_mm=float(bbox["y"]),
            max_bbox_z_mm=float(bbox["z"]),
            max_mass_g=float(brass["max_mass_g"]),
            shrinkage_linear=float(brass["shrinkage_linear"]),
        ),
    )
