"""Celery app and pipeline task.

Tasks receive a job_id and reconstruct their dependencies from Settings.
This keeps the task signature trivial to serialize (just a UUID) and the
actual wiring testable via the lower-level orchestrator.

For tests, set Celery to eager mode via ``app.conf.task_always_eager = True``
and the task runs synchronously in the caller's process.
"""

from __future__ import annotations

from uuid import UUID

from celery import Celery

from mos.config import get_settings
from mos.db import (
    CostSheetRepository,
    DesignSpecRepository,
    JobRepository,
    make_engine,
    make_session_factory,
)
from mos.schemas import BrassAlloy
from mos.storage import S3ObjectStore
from mos.worker.pipeline import PipelineConfig, run_pipeline

_settings = get_settings()

app = Celery(
    "mos",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_reject_on_worker_lost=True,
    # Phase 1: no fancy routing.
)


# --- Pipeline config loader ---------------------------------------------
#
# M10 uses hardcoded rates; M7 replaces this with a DB-backed rate fetcher
# and M11 adds per-job config overrides.

def _default_pipeline_config() -> PipelineConfig:
    return PipelineConfig(
        metal_rates_inr_per_kg={
            BrassAlloy.BRASS_70_30: 720.0,
            BrassAlloy.BRASS_85_15: 740.0,
            BrassAlloy.BRASS_65_35: 700.0,
        },
        inr_to_usd=0.012,
        yield_pct=None,  # use labor_rates.yaml default
        freight=None,
    )


# --- Task --------------------------------------------------------------

@app.task(name="mos.run_pipeline", bind=True)
def run_pipeline_task(self, job_id: str) -> dict:
    """Run the pipeline for one job and return a summary dict."""
    del self  # bind=True requires the parameter but we don't use it
    engine = make_engine(_settings.database_url)
    factory = make_session_factory(engine)

    store = S3ObjectStore(
        endpoint=_settings.storage_endpoint,
        access_key=_settings.storage_access_key,
        secret_key=_settings.storage_secret_key,
        bucket=_settings.storage_bucket,
        region=_settings.storage_region,
    )

    job = run_pipeline(
        UUID(job_id),
        job_repo=JobRepository(factory),
        spec_repo=DesignSpecRepository(factory),
        cost_repo=CostSheetRepository(factory),
        store=store,
        config=_default_pipeline_config(),
    )
    return {
        "job_id": str(job.job_id),
        "status": job.status.value,
        "bundle_uri": job.artifacts.bundle_zip_uri,
    }
