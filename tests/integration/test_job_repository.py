"""Integration tests for the repository layer. Require live Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mos.db import BriefRepository, JobNotFoundError, JobRepository
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


def _succeeded_stages() -> list[StageRecord]:
    now = datetime.now(timezone.utc)
    return [
        StageRecord(
            name=stage,
            status=StageStatus.SUCCEEDED,
            started_at=now,
            finished_at=now + timedelta(seconds=1),
        )
        for stage in StageName
    ]


def _make_job(owner_id, brief_id, *, status=JobStatus.QUEUED, stages=None) -> Job:
    return Job(
        owner_id=owner_id,
        brief_id=brief_id,
        status=status,
        stages=stages or _pending_stages(),
        snapshot=_snapshot(),
    )


class TestJobRepositoryCreateGet:
    def test_create_and_get_round_trips(
        self, session_factory: sessionmaker[Session]
    ):
        briefs = BriefRepository(session_factory)
        jobs = JobRepository(session_factory)

        owner = uuid4()
        brief_id = briefs.create(owner_id=owner, raw_text="antique brass planter")

        original = _make_job(owner, brief_id)
        jobs.create(original)

        fetched = jobs.get(original.job_id)
        # Equality check: Pydantic models compare by value, so this is a
        # thorough round-trip assertion.
        assert fetched == original

    def test_get_missing_raises(self, session_factory: sessionmaker[Session]):
        jobs = JobRepository(session_factory)
        with pytest.raises(JobNotFoundError):
            jobs.get(uuid4())

    def test_duplicate_create_raises_integrity_error(
        self, session_factory: sessionmaker[Session]
    ):
        briefs = BriefRepository(session_factory)
        jobs = JobRepository(session_factory)
        owner = uuid4()
        brief_id = briefs.create(owner_id=owner, raw_text="dup test")

        job = _make_job(owner, brief_id)
        jobs.create(job)
        with pytest.raises(IntegrityError):
            jobs.create(job)


class TestJobRepositoryList:
    def test_list_empty(self, session_factory: sessionmaker[Session]):
        jobs = JobRepository(session_factory)
        assert jobs.list_for_owner(uuid4()) == []

    def test_list_returns_most_recent_first(
        self, session_factory: sessionmaker[Session]
    ):
        briefs = BriefRepository(session_factory)
        jobs = JobRepository(session_factory)
        owner = uuid4()
        brief_id = briefs.create(owner_id=owner, raw_text="listing test")

        created_ids = []
        for _ in range(3):
            j = _make_job(owner, brief_id)
            jobs.create(j)
            created_ids.append(j.job_id)

        listed = jobs.list_for_owner(owner)
        assert len(listed) == 3
        assert {j.job_id for j in listed} == set(created_ids)
        # Most-recent-first: list is sorted descending by created_at.
        assert listed[0].created_at >= listed[-1].created_at

    def test_list_filters_by_status(
        self, session_factory: sessionmaker[Session]
    ):
        briefs = BriefRepository(session_factory)
        jobs = JobRepository(session_factory)
        owner = uuid4()
        brief_id = briefs.create(owner_id=owner, raw_text="status filter test")

        j_queued = _make_job(owner, brief_id, status=JobStatus.QUEUED)
        j_complete = _make_job(
            owner,
            brief_id,
            status=JobStatus.COMPLETE,
            stages=_succeeded_stages(),
        )
        jobs.create(j_queued)
        jobs.create(j_complete)

        only_complete = jobs.list_for_owner(owner, status=JobStatus.COMPLETE)
        assert [j.job_id for j in only_complete] == [j_complete.job_id]

    def test_list_scoped_to_owner(
        self, session_factory: sessionmaker[Session]
    ):
        briefs = BriefRepository(session_factory)
        jobs = JobRepository(session_factory)
        owner_a, owner_b = uuid4(), uuid4()
        brief_a = briefs.create(owner_id=owner_a, raw_text="a")
        brief_b = briefs.create(owner_id=owner_b, raw_text="b")
        jobs.create(_make_job(owner_a, brief_a))
        jobs.create(_make_job(owner_b, brief_b))

        a_jobs = jobs.list_for_owner(owner_a)
        b_jobs = jobs.list_for_owner(owner_b)
        assert len(a_jobs) == 1
        assert len(b_jobs) == 1
        assert a_jobs[0].owner_id == owner_a
        assert b_jobs[0].owner_id == owner_b

    def test_list_limit_bounds(self, session_factory: sessionmaker[Session]):
        jobs = JobRepository(session_factory)
        with pytest.raises(ValueError):
            jobs.list_for_owner(uuid4(), limit=0)
        with pytest.raises(ValueError):
            jobs.list_for_owner(uuid4(), limit=1000)
