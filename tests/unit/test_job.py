"""Tests for Job orchestration types and PipelineSnapshot reproducibility
record."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from mos.schemas import (
    Job,
    JobStatus,
    PipelineSnapshot,
    StageName,
    StageRecord,
    StageStatus,
)


def make_snapshot(**overrides) -> PipelineSnapshot:
    base = dict(
        schemas_version="1.0",
        template_id="candle_holder_classic_v1",
        template_version="v1.0",
        dfm_rules_version="sha256:abc123",
        cost_engine_version="0.1.0",
        sop_template_version="0.1.0",
        llm_provider="groq",
        llm_model="llama-3.1-70b-versatile",
        random_seed=42,
    )
    base.update(overrides)
    return PipelineSnapshot(**base)


def make_stages(all_succeeded: bool = True) -> list[StageRecord]:
    now = datetime.now(timezone.utc)
    status = StageStatus.SUCCEEDED if all_succeeded else StageStatus.PENDING
    return [
        StageRecord(
            name=stage,
            status=status,
            started_at=now if all_succeeded else None,
            finished_at=now + timedelta(seconds=1) if all_succeeded else None,
        )
        for stage in StageName
    ]


class TestStageRecord:
    def test_finished_without_started_rejected(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            StageRecord(
                name=StageName.CAD,
                status=StageStatus.SUCCEEDED,
                started_at=None,
                finished_at=now,
            )

    def test_finished_before_started_rejected(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(ValidationError):
            StageRecord(
                name=StageName.CAD,
                status=StageStatus.SUCCEEDED,
                started_at=now,
                finished_at=now - timedelta(seconds=5),
            )


class TestPipelineSnapshot:
    def test_valid_snapshot(self):
        s = make_snapshot()
        assert s.random_seed == 42

    def test_template_version_without_id_rejected(self):
        with pytest.raises(ValidationError, match="template_version"):
            make_snapshot(template_id=None, template_version="v1.0")

    def test_null_template_both_is_fine(self):
        # Valid when the LLM couldn't pick a template; no template, no version.
        s = make_snapshot(template_id=None, template_version=None)
        assert s.template_id is None


class TestJob:
    def test_complete_requires_all_stages_done(self):
        with pytest.raises(
            ValidationError, match="COMPLETE job must have all stages"
        ):
            Job(
                owner_id=uuid4(),
                brief_id=uuid4(),
                status=JobStatus.COMPLETE,
                stages=make_stages(all_succeeded=False),
                snapshot=make_snapshot(),
            )

    def test_failed_requires_a_failed_stage(self):
        with pytest.raises(
            ValidationError, match="FAILED job must have"
        ):
            Job(
                owner_id=uuid4(),
                brief_id=uuid4(),
                status=JobStatus.FAILED,
                stages=make_stages(all_succeeded=True),  # none failed
                snapshot=make_snapshot(),
            )

    def test_running_job_is_valid_regardless_of_stages(self):
        Job(
            owner_id=uuid4(),
            brief_id=uuid4(),
            status=JobStatus.RUNNING,
            stages=make_stages(all_succeeded=False),
            snapshot=make_snapshot(),
        )
