"""Integration test for MetalRateRepository.

The repository's job: persist rate snapshots and read the most recent.
The unique index on (metal, rate_date) makes the upsert idempotent for a
day. We verify both behaviors against real Postgres.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mos.db import MetalRateRepository


def _midnight(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)


class TestMetalRateRepository:
    def test_upsert_and_latest(self, session_factory):
        repo = MetalRateRepository(session_factory)
        today = _midnight(datetime.now(timezone.utc))
        repo.upsert_for_date(
            metal="brass_70_30",
            rate_per_kg_inr=720.0,
            source="test_source",
            rate_date=today,
        )
        latest = repo.latest("brass_70_30")
        assert latest is not None
        assert latest.rate_per_kg_inr == 720.0
        assert latest.source == "test_source"

    def test_latest_returns_most_recent_date(self, session_factory):
        repo = MetalRateRepository(session_factory)
        today = _midnight(datetime.now(timezone.utc))
        yesterday = today - timedelta(days=1)
        repo.upsert_for_date(
            metal="brass_70_30", rate_per_kg_inr=695.0,
            source="t", rate_date=yesterday,
        )
        repo.upsert_for_date(
            metal="brass_70_30", rate_per_kg_inr=720.0,
            source="t", rate_date=today,
        )
        latest = repo.latest("brass_70_30")
        assert latest.rate_per_kg_inr == 720.0

    def test_upsert_is_idempotent_per_day(self, session_factory):
        """Two writes for the same (metal, rate_date) don't raise; first
        wins (ON CONFLICT DO NOTHING)."""
        repo = MetalRateRepository(session_factory)
        today = _midnight(datetime.now(timezone.utc))
        repo.upsert_for_date(
            metal="brass_70_30", rate_per_kg_inr=720.0,
            source="t", rate_date=today,
        )
        repo.upsert_for_date(
            metal="brass_70_30", rate_per_kg_inr=999.0,
            source="t2", rate_date=today,
        )
        latest = repo.latest("brass_70_30")
        # First write retained.
        assert latest.rate_per_kg_inr == 720.0
        assert latest.source == "t"

    def test_latest_returns_none_when_empty(self, session_factory):
        repo = MetalRateRepository(session_factory)
        assert repo.latest("brass_85_15") is None

    def test_metal_keys_are_isolated(self, session_factory):
        repo = MetalRateRepository(session_factory)
        today = _midnight(datetime.now(timezone.utc))
        repo.upsert_for_date(
            metal="brass_70_30", rate_per_kg_inr=720.0,
            source="t", rate_date=today,
        )
        repo.upsert_for_date(
            metal="brass_85_15", rate_per_kg_inr=850.0,
            source="t", rate_date=today,
        )
        a = repo.latest("brass_70_30")
        b = repo.latest("brass_85_15")
        assert a.rate_per_kg_inr == 720.0
        assert b.rate_per_kg_inr == 850.0
