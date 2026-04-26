"""Unit tests for the Pydantic <-> ORM conversion helpers in repository.py.

These are pure functions; they don't need a database. The full CRUD round-trip
tests live in tests/integration/test_job_repository.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from mos.db.repository import _job_to_row, _row_to_job
from mos.schemas import (
    Job,
    JobStatus,
    PipelineSnapshot,
    StageName,
    StageRecord,
    StageStatus,
)


def _snapshot() -> PipelineSnapshot:
    return PipelineSnapshot(
        schemas_version="1.0",
        template_id="candle_holder_classic_v1",
        template_version="v1.0",
        dfm_rules_version="sha256:abc",
        cost_engine_version="0.1.0",
        sop_template_version="0.1.0",
        llm_model="llama-3.1-70b-versatile",
        random_seed=7,
    )


def _pending_stages() -> list[StageRecord]:
    return [
        StageRecord(name=stage, status=StageStatus.PENDING)
        for stage in StageName
    ]


class TestConversionRoundTrip:
    def test_queued_job_round_trip(self):
        job = Job(
            owner_id=uuid4(),
            brief_id=uuid4(),
            status=JobStatus.QUEUED,
            stages=_pending_stages(),
            snapshot=_snapshot(),
        )
        row = _job_to_row(job)
        # After conversion, the row must carry the scalar fields for querying
        assert row.job_id == job.job_id
        assert row.status == JobStatus.QUEUED.value
        assert isinstance(row.stages, list)
        assert len(row.stages) == len(job.stages)

        rebuilt = _row_to_job(row)
        assert rebuilt == job

    def test_complete_job_round_trip(self):
        now = datetime.now(timezone.utc)
        stages = [
            StageRecord(
                name=stage,
                status=StageStatus.SUCCEEDED,
                started_at=now,
                finished_at=now + timedelta(seconds=1),
            )
            for stage in StageName
        ]
        job = Job(
            owner_id=uuid4(),
            brief_id=uuid4(),
            status=JobStatus.COMPLETE,
            stages=stages,
            snapshot=_snapshot(),
        )
        rebuilt = _row_to_job(_job_to_row(job))
        assert rebuilt == job
