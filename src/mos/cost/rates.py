"""Load labor, overhead, and margin rates from config/labor_rates.yaml.

Same pattern as mos.cad.rules: content-hashed, factory-tunable, version
recorded in PipelineSnapshot.cost_engine_version via the caller.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PlatingRates:
    nickel_inr: float
    silver_inr: float
    gold_inr: float

    def rate_for(self, plating: str) -> float:
        if plating == "nickel":
            return self.nickel_inr
        if plating == "silver":
            return self.silver_inr
        if plating == "gold":
            return self.gold_inr
        if plating == "none":
            return 0.0
        raise ValueError(f"unknown plating type: {plating!r}")


@dataclass(frozen=True)
class LaborRates:
    casting_per_kg_raw_inr: float
    scraping_per_piece_inr: float
    chasing_per_piece_inr: float
    polishing_per_piece_inr: float


@dataclass(frozen=True)
class FinishingRates:
    lacquer_per_piece_inr: float
    plating: PlatingRates


@dataclass(frozen=True)
class CostRates:
    version: str
    content_hash: str  # "sha256:...", used for PipelineSnapshot
    default_yield_pct: float
    finishing_loss_pct: float
    labor: LaborRates
    finishing: FinishingRates
    packing_per_piece_inr: float
    overhead_pct: float
    margin_pct: float


def _default_rates_path() -> Path:
    return Path(__file__).resolve().parents[3] / "config" / "labor_rates.yaml"


def load_cost_rates(path: Path | None = None) -> CostRates:
    p = path or _default_rates_path()
    raw = p.read_bytes()
    content_hash = "sha256:" + hashlib.sha256(raw).hexdigest()[:16]
    data = yaml.safe_load(raw)

    labor = data["labor"]
    finishing = data["finishing"]
    plating = finishing["plating_per_piece_inr"]

    return CostRates(
        version=data["version"],
        content_hash=content_hash,
        default_yield_pct=float(data["default_yield_pct"]),
        finishing_loss_pct=float(data["material"]["finishing_loss_pct"]),
        labor=LaborRates(
            casting_per_kg_raw_inr=float(labor["casting_per_kg_raw_inr"]),
            scraping_per_piece_inr=float(labor["scraping_per_piece_inr"]),
            chasing_per_piece_inr=float(labor["chasing_per_piece_inr"]),
            polishing_per_piece_inr=float(labor["polishing_per_piece_inr"]),
        ),
        finishing=FinishingRates(
            lacquer_per_piece_inr=float(finishing["lacquer_per_piece_inr"]),
            plating=PlatingRates(
                nickel_inr=float(plating["nickel"]),
                silver_inr=float(plating["silver"]),
                gold_inr=float(plating["gold"]),
            ),
        ),
        packing_per_piece_inr=float(data["packing_per_piece_inr"]),
        overhead_pct=float(data["overhead_pct"]),
        margin_pct=float(data["margin_pct"]),
    )
