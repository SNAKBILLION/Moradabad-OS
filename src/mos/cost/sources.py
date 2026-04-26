"""Rate sources for metal prices and foreign-exchange.

Phase 1 ships only manual sources — the caller supplies the rate, the source
wraps it in a frozen snapshot for traceability. M7 adds HTTP-backed sources
with cache fallback against the metal_rates and fx_rates DB tables.

Sources are pluggable via Protocol so the cost engine doesn't know whether
a rate came from a human, a website, or a cached DB row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from mos.schemas import BrassAlloy, FxSnapshot, MetalRate


@runtime_checkable
class MetalRateSource(Protocol):
    def fetch(self, alloy: BrassAlloy) -> MetalRate: ...


@runtime_checkable
class FxSource(Protocol):
    def fetch(self) -> FxSnapshot: ...


# --- Manual sources ------------------------------------------------------

class ManualMetalRateSource:
    """Wraps hardcoded rates for Phase 1 testing and pre-calibration use.

    Rates are a dict {alloy: rate_per_kg_inr}. fetched_at is set to 'now' at
    fetch time, source is 'manual'.
    """

    def __init__(self, rates_inr_per_kg: dict[BrassAlloy, float]) -> None:
        for v in rates_inr_per_kg.values():
            if v <= 0:
                raise ValueError("metal rates must be > 0")
        self._rates = dict(rates_inr_per_kg)

    def fetch(self, alloy: BrassAlloy) -> MetalRate:
        if alloy not in self._rates:
            raise KeyError(f"no manual rate configured for {alloy.value}")
        return MetalRate(
            rate_per_kg_inr=self._rates[alloy],
            source="manual",
            fetched_at=datetime.now(timezone.utc),
            stale=False,
        )


class ManualFxSource:
    """Wraps a hardcoded INR->USD rate."""

    def __init__(self, inr_to_usd: float) -> None:
        if inr_to_usd <= 0:
            raise ValueError("inr_to_usd must be > 0")
        self._rate = inr_to_usd

    def fetch(self) -> FxSnapshot:
        return FxSnapshot(
            inr_to_usd=self._rate,
            source="manual",
            fetched_at=datetime.now(timezone.utc),
        )
