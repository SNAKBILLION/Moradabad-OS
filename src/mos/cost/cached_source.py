"""Cached metal rate source.

Wraps any MetalRateSource. On primary success: persists the result and
returns it. On primary failure: returns the most recent cached rate for the
metal with ``stale=True`` so the cost engine surfaces it in the sheet's
assumptions list (this wiring already exists from M6 — see
mos.cost.engine.compute_cost_sheet).

A single ``stale=True`` snapshot in a cost sheet is the user-visible signal
that something upstream is broken and the rate should be reviewed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mos.cost.http_source import MetalRateFetchError
from mos.cost.sources import MetalRateSource
from mos.db.repository import MetalRateRepository
from mos.schemas import BrassAlloy, MetalRate


class NoCachedRateError(LookupError):
    """Raised when primary fails AND no cached rate exists for the metal."""


class CachedMetalRateSource:
    """Decorator: any MetalRateSource + a MetalRateRepository.

    On every fetch:
      1. Call primary.
      2. If primary returns: persist (idempotent on day) and return.
      3. If primary raises: read latest cached, return with stale=True.
      4. If no cache exists: raise NoCachedRateError. Caller decides whether
         to fail the job or fall back to a manual override.

    The decision to fail-or-fall-back is the caller's, not the cache's. We
    don't want this layer making policy decisions about pipeline behavior.
    """

    def __init__(
        self,
        primary: MetalRateSource,
        repo: MetalRateRepository,
    ) -> None:
        self._primary = primary
        self._repo = repo

    def fetch(self, alloy: BrassAlloy) -> MetalRate:
        metal_key = alloy.value  # "brass_70_30" etc — matches metal_rates.metal
        try:
            fresh = self._primary.fetch(alloy)
        except (MetalRateFetchError, KeyError) as primary_err:
            cached = self._repo.latest(metal_key)
            if cached is None:
                raise NoCachedRateError(
                    f"primary failed and no cached rate for {metal_key}: "
                    f"{primary_err}"
                ) from primary_err
            return MetalRate(
                rate_per_kg_inr=cached.rate_per_kg_inr,
                source=f"{cached.source} (cached)",
                fetched_at=cached.fetched_at,
                stale=True,
            )

        # Primary succeeded — persist for future fallback. ON CONFLICT DO
        # NOTHING so multiple fetches the same day don't pile up.
        # Use date-only granularity (zero out time) so "today" collapses
        # to one row regardless of when in the day we fetched.
        rate_date = fresh.fetched_at.replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
        )
        self._repo.upsert_for_date(
            metal=metal_key,
            rate_per_kg_inr=fresh.rate_per_kg_inr,
            source=fresh.source,
            rate_date=rate_date,
        )
        return fresh
