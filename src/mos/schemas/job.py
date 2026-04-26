"""Job: the orchestration record tracking a single brief through the pipeline.

Also defines PipelineSnapshot, the per-job record of all component versions
used to produce the artifacts. This is the Path-C reproducibility requirement:
given a JobSnapshot and the same input brief, the system must be able to
regenerate byte-identical artifacts (modulo timestamps).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETE = "complete"
    FAILED = "failed"


class StageName(str, Enum):
    INTENT = "intent"
    CAD = "cad"
    COST = "cost"
    SOP = "sop"
    RENDER = "render"
    BUNDLE = "bundle"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"  # feature-flag disabled


class StageRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: StageName
    status: StageStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _times_consistent(self) -> StageRecord:
        if self.finished_at is not None and self.started_at is None:
            raise ValueError("finished_at set without started_at")
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("finished_at precedes started_at")
        return self


class ArtifactBundle(BaseModel):
    """URIs (object-store keys) for every artifact a job produces.

    Keys are None until their respective stage succeeds. A COMPLETE job has
    step_uri, stl_uri, shop_drawing_pdf_uri, sop_pdf_uri, cost_sheet_json_uri,
    and bundle_zip_uri all populated. render_png_uris may be empty if the
    render feature flag is disabled.
    """

    model_config = ConfigDict(frozen=True)

    step_uri: str | None = None
    stl_uri: str | None = None
    dxf_uri: str | None = None
    shop_drawing_pdf_uri: str | None = None
    sop_pdf_uri: str | None = None
    render_png_uris: list[str] = Field(default_factory=list)
    cost_sheet_json_uri: str | None = None
    bundle_zip_uri: str | None = None


class PipelineSnapshot(BaseModel):
    """Immutable record of all component versions used by a single job.

    Required by Path-C reproducibility: replaying a brief against the same
    snapshot must produce the same artifacts.
    """

    model_config = ConfigDict(frozen=True)

    # Our own versions
    schemas_version: str  # matches design_spec.SCHEMA_VERSION at runtime
    template_id: str | None
    template_version: str | None  # e.g. "candle_holder_v1.2"
    dfm_rules_version: str  # hash or version tag of dfm_rules.yaml
    cost_engine_version: str
    sop_template_version: str

    # External model versions
    llm_provider: str = "groq"
    llm_model: str  # e.g. "llama-3.1-70b-versatile"

    # Random-seed inputs — pinned so the render and any sampling are
    # deterministic when the same snapshot is replayed.
    random_seed: int = Field(ge=0)

    @model_validator(mode="after")
    def _template_version_requires_id(self) -> PipelineSnapshot:
        if self.template_version is not None and self.template_id is None:
            raise ValueError(
                "template_version set without template_id"
            )
        return self


class Job(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID = Field(default_factory=uuid4)
    owner_id: UUID
    brief_id: UUID
    spec_id: UUID | None = None  # set after intent stage succeeds
    status: JobStatus
    stages: list[StageRecord]
    artifacts: ArtifactBundle = Field(default_factory=ArtifactBundle)
    snapshot: PipelineSnapshot
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def _status_matches_stages(self) -> Job:
        # Sanity checks that catch orchestrator bugs early.
        if self.status == JobStatus.COMPLETE:
            if not all(
                s.status in (StageStatus.SUCCEEDED, StageStatus.SKIPPED)
                for s in self.stages
            ):
                raise ValueError(
                    "COMPLETE job must have all stages SUCCEEDED or SKIPPED"
                )
        if self.status == JobStatus.FAILED:
            if not any(s.status == StageStatus.FAILED for s in self.stages):
                raise ValueError(
                    "FAILED job must have at least one FAILED stage"
                )
        return self
