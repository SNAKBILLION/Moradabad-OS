"""FastAPI app.

Endpoints (M10):
  POST /jobs       : submit a DesignSpec, create a Job, enqueue pipeline
  GET  /jobs/{id}  : get current job status + artifact URIs
  GET  /healthz    : liveness

IMPORTANT — no authentication in M10. ``owner_id`` is accepted as a request
field. This API is safe only behind a trusted network; wiring JWT is M12+.

Endpoints do not expose raw object-store URIs; they translate to presigned
URLs at response time. That way rotating credentials or changing buckets
doesn't invalidate stored job records.
"""

from __future__ import annotations

import hmac
import io
import os
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import APIKeyHeader
from fastapi import Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from botocore.exceptions import ClientError
from pathlib import Path as _UIPath
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from mos.config import Settings, get_settings
from mos.db import (
    BriefRepository,
    DesignSpecRepository,
    FeedbackNotFoundError,
    FeedbackRepository,
    JobNotFoundError,
    JobRepository,
    LlmCallRepository,
    make_engine,
    make_session_factory,
)
from mos.intent import build_intent_from_brief
from mos.schemas import (
    ArtifactBundle,
    DesignSpec,
    FeedbackPayload,
    FeedbackRecord,
    Job,
    JobStatus,
    PipelineSnapshot,
    SCHEMA_VERSION,
    StageName,
    StageRecord,
    StageStatus,
    UserRole,
)
from mos.storage import S3ObjectStore
from mos.templates import default_registry


# --- API key auth -------------------------------------------------------
#
# Single shared key, read from MOS_API_KEY env var. Falls back to the
# pilot literal if the env is unset. Override the env on any non-local
# deploy. /healthz remains open so load balancers and monitoring can
# reach it without credentials.

_API_KEY = os.environ.get("MOS_API_KEY", "moradabad-secret-123")

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


def verify_key(api_key: str | None = Depends(api_key_header)) -> None:
    """Reject the request unless x-api-key matches the configured key."""
    if api_key is None:
        raise HTTPException(status_code=401, detail="missing x-api-key header")
    if not hmac.compare_digest(api_key, _API_KEY):
        raise HTTPException(status_code=401, detail="invalid x-api-key")


# --- Dependency wiring --------------------------------------------------
#
# FastAPI's Depends gives us clean injection points. Tests override these
# to supply a test-scoped session factory and in-memory storage.

def get_session_factory() -> sessionmaker[Session]:
    """Build the default session factory from settings.

    Overridden in tests via app.dependency_overrides. Not cached here — the
    test overrides need to return a specific transaction-scoped factory.
    """
    settings = get_settings()
    return make_session_factory(make_engine(settings.database_url))


def get_store():
    settings = get_settings()
    return S3ObjectStore(
        endpoint=settings.storage_endpoint,
        access_key=settings.storage_access_key,
        secret_key=settings.storage_secret_key,
        bucket=settings.storage_bucket,
        region=settings.storage_region,
    )


def get_intent_client():
    """Build a GroqClient from settings.

    Overridden in tests to inject a mock that doesn't hit the network. If
    ``GROQ_API_KEY`` is unset, this returns None — the API will then reject
    brief-only requests with a 503 explaining the misconfiguration.
    """
    settings = get_settings()
    if not settings.groq_api_key:
        return None
    from mos.intent import GroqClient

    return GroqClient(api_key=settings.groq_api_key, model=settings.groq_model)


def enqueue_pipeline(job_id: UUID) -> None:
    """Hand the job to Celery. Overridden in tests to run synchronously."""
    from mos.worker.app import run_pipeline_task

    run_pipeline_task.delay(str(job_id))


# --- Request / response models ------------------------------------------

class JobCreateRequest(BaseModel):
    """Request shape for POST /jobs.

    Either ``design_spec`` is supplied directly (M10 path, useful for
    testing and for callers that already have a structured spec) OR the
    server runs the intent layer on ``brief_text`` to produce one.

    If both are provided, the explicit ``design_spec`` wins — the intent
    layer is skipped.
    """

    model_config = ConfigDict(frozen=True)

    owner_id: UUID
    brief_text: str = Field(min_length=1, max_length=4000)
    design_spec: DesignSpec | None = None


class ArtifactUrls(BaseModel):
    """Presigned URLs for artifacts. Keys matching ArtifactBundle fields."""

    model_config = ConfigDict(frozen=True)

    step: str | None = None
    stl: str | None = None
    dxf: str | None = None
    shop_drawing_pdf: str | None = None
    sop_pdf: str | None = None
    cost_sheet_json: str | None = None
    bundle_zip: str | None = None


class JobResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID
    status: JobStatus
    stages: list[StageRecord]
    artifact_urls: ArtifactUrls
    intent_reason: str | None = None  # populated when status==AWAITING_REVIEW


# --- Feedback request / response ----------------------------------------

class FeedbackCreateRequest(BaseModel):
    """Body for POST /jobs/{job_id}/feedback.

    feedback_id and created_at are server-generated; clients never set them.
    job_id comes from the URL path, not the body.
    """

    model_config = ConfigDict(frozen=True)

    user_role: UserRole
    payload: FeedbackPayload = Field(discriminator="type")
    notes_text: str = Field(default="", max_length=2000)


class FeedbackResponse(BaseModel):
    """The full FeedbackRecord, identical wire shape to the schema model."""

    model_config = ConfigDict(frozen=True)

    feedback_id: UUID
    job_id: UUID
    user_role: UserRole
    payload: FeedbackPayload = Field(discriminator="type")
    notes_text: str
    created_at: datetime


def _feedback_to_response(record: FeedbackRecord) -> FeedbackResponse:
    return FeedbackResponse(
        feedback_id=record.feedback_id,
        job_id=record.job_id,
        user_role=record.user_role,
        payload=record.payload,
        notes_text=record.notes_text,
        created_at=record.created_at,
    )


# --- App ----------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="Moradabad AI Design + Production OS",
        version="0.1.0-m10",
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/jobs", response_model=JobResponse, status_code=201)
    def create_job(
        req: JobCreateRequest,
        factory: sessionmaker[Session] = Depends(get_session_factory),
        store=Depends(get_store),
        intent_client=Depends(get_intent_client),
        _: None = Depends(verify_key),
    ) -> JobResponse:
        briefs = BriefRepository(factory)
        specs = DesignSpecRepository(factory)
        jobs = JobRepository(factory)
        llm_log = LlmCallRepository(factory)

        # Decide which path: caller-supplied spec vs run-the-LLM.
        # Either way, we end up with (brief_id, spec_or_None, llm_model_label).
        if req.design_spec is not None:
            spec: DesignSpec | None = req.design_spec
            brief_id = spec.brief_id
            llm_model_label = "not-used"
            intent_reason: str | None = None
        else:
            if intent_client is None:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Intent layer requires GROQ_API_KEY. Either configure "
                        "the server or supply design_spec directly."
                    ),
                )
            # Persist the brief BEFORE calling Groq so the FK constraint on
            # llm_calls.brief_id is satisfied for every recorded attempt
            # (including failures).
            brief_id = uuid4()
            briefs.create_with_id(
                brief_id=brief_id,
                owner_id=req.owner_id,
                raw_text=req.brief_text,
            )
            registry = list(default_registry().values())
            result = build_intent_from_brief(
                brief_id=brief_id,
                brief_text=req.brief_text,
                templates=registry,
                client=intent_client,
                sink=llm_log,
            )
            spec = result.spec
            intent_reason = result.reason
            llm_model_label = (
                intent_client.model if intent_client is not None else "unknown"
            )

        # If we had a spec from the caller, persist the brief now (the
        # intent path already did so above).
        if req.design_spec is not None:
            briefs.create_with_id(
                brief_id=brief_id,
                owner_id=req.owner_id,
                raw_text=req.brief_text,
            )
            specs.create(spec)

        snapshot = PipelineSnapshot(
            schemas_version=SCHEMA_VERSION,
            template_id=spec.template_id if spec is not None else None,
            template_version="v1.0" if spec and spec.template_id else None,
            dfm_rules_version="runtime",
            cost_engine_version="runtime",
            sop_template_version="not-implemented",
            llm_model=llm_model_label,
            random_seed=0,
        )
        stages = [
            StageRecord(name=s, status=StageStatus.PENDING) for s in StageName
        ]

        # If intent failed, halt the job in AWAITING_REVIEW and do not
        # enqueue the pipeline.
        if spec is None:
            job = Job(
                owner_id=req.owner_id,
                brief_id=brief_id,
                spec_id=None,
                status=JobStatus.AWAITING_REVIEW,
                stages=stages,
                artifacts=ArtifactBundle(),
                snapshot=snapshot,
            )
            jobs.create(job)
            return _to_response(
                jobs.get(job.job_id), store, intent_reason=intent_reason
            )

        # Persist the spec produced by intent (skipped above if caller-supplied
        # because we did it in that branch already).
        if req.design_spec is None:
            specs.create(spec)

        job = Job(
            owner_id=req.owner_id,
            brief_id=brief_id,
            spec_id=spec.spec_id,
            status=JobStatus.QUEUED,
            stages=stages,
            artifacts=ArtifactBundle(),
            snapshot=snapshot,
        )
        jobs.create(job)
        enqueue_pipeline(job.job_id)
        return _to_response(jobs.get(job.job_id), store)

    @app.get("/jobs/{job_id}", response_model=JobResponse)
    def get_job(
        job_id: UUID,
        factory: sessionmaker[Session] = Depends(get_session_factory),
        store=Depends(get_store),
        _: None = Depends(verify_key),
    ) -> JobResponse:
        jobs = JobRepository(factory)
        try:
            job = jobs.get(job_id)
        except JobNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return _to_response(job, store)

    # --- Feedback routes (M11a) -----------------------------------------

    @app.post(
        "/jobs/{job_id}/feedback",
        response_model=FeedbackResponse,
        status_code=201,
    )
    def create_feedback(
        job_id: UUID,
        req: FeedbackCreateRequest,
        factory: sessionmaker[Session] = Depends(get_session_factory),
        _: None = Depends(verify_key),
    ) -> FeedbackResponse:
        # Verify the job exists before recording feedback. The DB FK will
        # also reject orphans (RESTRICT), but a 404 here is clearer than a
        # 500 caused by an IntegrityError surfacing.
        jobs = JobRepository(factory)
        try:
            jobs.get(job_id)
        except JobNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

        record = FeedbackRecord(
            job_id=job_id,
            user_role=req.user_role,
            payload=req.payload,
            notes_text=req.notes_text,
        )
        FeedbackRepository(factory).create(record)
        return _feedback_to_response(record)

    @app.get(
        "/jobs/{job_id}/feedback",
        response_model=list[FeedbackResponse],
    )
    def list_feedback_for_job(
        job_id: UUID,
        limit: int = 100,
        factory: sessionmaker[Session] = Depends(get_session_factory),
        _: None = Depends(verify_key),
    ) -> list[FeedbackResponse]:
        # No 404 if the job has no feedback yet — empty list is the right
        # answer. We only return 422 on bad limit values.
        if limit < 1 or limit > 1000:
            raise HTTPException(
                status_code=422, detail="limit must be between 1 and 1000"
            )
        records = FeedbackRepository(factory).list_for_job(job_id, limit=limit)
        return [_feedback_to_response(r) for r in records]

    @app.get(
        "/feedback/{feedback_id}",
        response_model=FeedbackResponse,
    )
    def get_feedback(
        feedback_id: UUID,
        factory: sessionmaker[Session] = Depends(get_session_factory),
        _: None = Depends(verify_key),
    ) -> FeedbackResponse:
        try:
            record = FeedbackRepository(factory).get(feedback_id)
        except FeedbackNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return _feedback_to_response(record)

    @app.get(
        "/jobs/{job_id}/render/{spec_id}.png",
    )
    def get_render_png(
        job_id: UUID,
        spec_id: str,
        key: str | None = None,
        api_key_hdr: str | None = Depends(api_key_header),
        store=Depends(get_store),
    ) -> Response:
        # Accept key via header OR query param so <img> tags work in the UI.
        provided = api_key_hdr or key
        if not provided or not hmac.compare_digest(provided, _API_KEY):
            raise HTTPException(status_code=401, detail="invalid api key")
        uri = f"s3://{store.bucket}/jobs/{job_id}/render/{spec_id}.png"
        try:
            data = store.get_bytes(uri)
        except (KeyError, ClientError) as e:
            raise HTTPException(status_code=404, detail=f"render not found: {e}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"render fetch failed: {e}")
        return StreamingResponse(io.BytesIO(data), media_type="image/png")

    _ui_dir = _UIPath(__file__).resolve().parent / "ui"
    if _ui_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=str(_ui_dir), html=True), name="ui")


    return app


def _to_response(job: Job, store, *, intent_reason: str | None = None) -> JobResponse:
    """Build a JobResponse with presigned URLs for any populated artifacts."""
    b = job.artifacts

    def _sign(uri: str | None) -> str | None:
        if uri is None:
            return None
        return store.presigned_url(uri)

    urls = ArtifactUrls(
        step=_sign(b.step_uri),
        stl=_sign(b.stl_uri),
        dxf=_sign(b.dxf_uri),
        shop_drawing_pdf=_sign(b.shop_drawing_pdf_uri),
        sop_pdf=_sign(b.sop_pdf_uri),
        cost_sheet_json=_sign(b.cost_sheet_json_uri),
        bundle_zip=_sign(b.bundle_zip_uri),
    )
    return JobResponse(
        job_id=job.job_id,
        status=job.status,
        stages=list(job.stages),
        artifact_urls=urls,
        intent_reason=intent_reason,
    )


# Module-level app instance for `uvicorn mos.api.app:app`.
app = create_app()
