"""Unit tests for CachedMetalRateSource.

The repo is faked here — full DB round-trip is in
tests/integration/test_metal_rate_repository.py.

The milestone success criterion: source-outage test falls back to cache and
flags ``stale: true``. ``test_outage_returns_stale_cached`` is that test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mos.cost import (
    CachedMetalRateSource,
    MetalRateFetchError,
    NoCachedRateError,
)
from mos.schemas import BrassAlloy, MetalRate


# --- Test fakes ---------------------------------------------------------

class _FakePrimary:
    """Returns a queue of MetalRate values or raises queued exceptions."""

    def __init__(self, items: list) -> None:
        self._queue = list(items)
        self.calls: list[BrassAlloy] = []

    def fetch(self, alloy: BrassAlloy) -> MetalRate:
        self.calls.append(alloy)
        if not self._queue:
            raise AssertionError("primary exhausted")
        head = self._queue.pop(0)
        if isinstance(head, Exception):
            raise head
        return head


class _FakeRepo:
    """In-memory MetalRateRepository stand-in. Supports latest/upsert."""

    def __init__(self) -> None:
        # {metal: list of dict-rows}
        self._rows: dict[str, list[dict]] = {}

    def latest(self, metal: str):
        rows = self._rows.get(metal, [])
        if not rows:
            return None
        # latest = max rate_date
        sorted_rows = sorted(rows, key=lambda r: r["rate_date"], reverse=True)
        # Repository normally returns ORM rows; mimic by exposing attrs.
        return SimpleNamespace(**sorted_rows[0])

    def upsert_for_date(
        self, *, metal: str, rate_per_kg_inr: float, source: str,
        rate_date: datetime,
    ) -> None:
        rows = self._rows.setdefault(metal, [])
        for r in rows:
            if r["rate_date"] == rate_date:
                # ON CONFLICT DO NOTHING — keep the existing row, ignore new.
                return
        rows.append(
            {
                "metal": metal,
                "rate_per_kg_inr": rate_per_kg_inr,
                "source": source,
                "rate_date": rate_date,
                "fetched_at": datetime.now(timezone.utc),
            }
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rate(value: float = 720.0, *, source: str = "test_indicator") -> MetalRate:
    return MetalRate(
        rate_per_kg_inr=value,
        source=source,
        fetched_at=_now(),
        stale=False,
    )


# --- Tests --------------------------------------------------------------

class TestPrimarySuccess:
    def test_returns_fresh_rate(self):
        primary = _FakePrimary([_rate(703.0)])
        cache = _FakeRepo()
        src = CachedMetalRateSource(primary, cache)
        result = src.fetch(BrassAlloy.BRASS_70_30)
        assert result.rate_per_kg_inr == 703.0
        assert result.stale is False
        assert result.source == "test_indicator"

    def test_persists_to_cache_on_success(self):
        primary = _FakePrimary([_rate(703.0)])
        cache = _FakeRepo()
        src = CachedMetalRateSource(primary, cache)
        src.fetch(BrassAlloy.BRASS_70_30)
        latest = cache.latest("brass_70_30")
        assert latest is not None
        assert latest.rate_per_kg_inr == 703.0

    def test_idempotent_on_same_day(self):
        # Same fetch twice -> only one cache row (ON CONFLICT DO NOTHING).
        primary = _FakePrimary([_rate(703.0), _rate(800.0)])
        cache = _FakeRepo()
        src = CachedMetalRateSource(primary, cache)
        src.fetch(BrassAlloy.BRASS_70_30)
        src.fetch(BrassAlloy.BRASS_70_30)
        # Both calls hit primary (we don't dedupe at the source level), but
        # only the first writes to cache.
        rows = cache._rows["brass_70_30"]
        assert len(rows) == 1
        # First write wins.
        assert rows[0]["rate_per_kg_inr"] == 703.0


class TestPrimaryFailure:
    def test_outage_returns_stale_cached(self):
        """Milestone success criterion: source outage -> cached + stale=True."""
        cache = _FakeRepo()
        # Pre-populate the cache.
        yesterday = (_now() - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cache._rows["brass_70_30"] = [
            {
                "metal": "brass_70_30",
                "rate_per_kg_inr": 695.0,
                "source": "test_indicator",
                "rate_date": yesterday,
                "fetched_at": yesterday,
            }
        ]
        primary = _FakePrimary([MetalRateFetchError("upstream is down")])
        src = CachedMetalRateSource(primary, cache)

        result = src.fetch(BrassAlloy.BRASS_70_30)
        assert result.stale is True
        assert result.rate_per_kg_inr == 695.0
        assert "cached" in result.source
        assert "test_indicator" in result.source

    def test_unknown_alloy_falls_back_to_cache(self):
        # Primary raises KeyError for unknown alloy — also a fallback case.
        cache = _FakeRepo()
        cache._rows["brass_85_15"] = [
            {
                "metal": "brass_85_15",
                "rate_per_kg_inr": 800.0,
                "source": "test",
                "rate_date": _now(),
                "fetched_at": _now(),
            }
        ]
        primary = _FakePrimary([KeyError("brass_85_15")])
        src = CachedMetalRateSource(primary, cache)
        result = src.fetch(BrassAlloy.BRASS_85_15)
        assert result.stale is True
        assert result.rate_per_kg_inr == 800.0

    def test_no_cache_raises_typed_error(self):
        primary = _FakePrimary([MetalRateFetchError("down")])
        cache = _FakeRepo()  # empty
        src = CachedMetalRateSource(primary, cache)
        with pytest.raises(NoCachedRateError):
            src.fetch(BrassAlloy.BRASS_70_30)
