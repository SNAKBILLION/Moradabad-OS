"""Pipeline orchestrator.

Takes a queued Job + its DesignSpec and drives it to completion. Each stage:
  1. Flags the job as RUNNING with this stage in progress
  2. Executes the stage's work
  3. Persists artifacts to object storage
  4. Updates the job record in DB with new artifact URIs
  5. Marks the stage SUCCEEDED

On any exception, the offending stage is marked FAILED, the job is marked
FAILED, and the exception is re-raised so the worker logs it. There is no
automatic retry in M10 (deferred).

Stages implemented:
  - CAD     : geometry build + DFM + export STEP+STL
  - COST    : compute cost sheet; persist to cost_sheets table
  - BUNDLE  : zip artifacts + upload, record bundle_uri

Stages not implemented (hard-coded SKIPPED):
  - INTENT  : LLM lands in M11; for M10 caller supplies DesignSpec directly
  - SOP     : lands in M8
  - RENDER  : lands in M9
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from mos.cad import run_cad
from mos.cost import (
    FreightInput,
    ManualFxSource,
    ManualMetalRateSource,
    compute_cost_sheet,
    load_cost_rates,
)
from mos.db.repository import (
    CostSheetRepository,
    DesignSpecRepository,
    JobRepository,
)
from mos.render import (
    BlenderNotFoundError,
    BlenderRenderError,
    RenderOptions,
    render_stl,
)
from mos.schemas import (
    ArtifactBundle,
    BrassAlloy,
    DesignSpec,
    Job,
    JobStatus,
    StageName,
    StageRecord,
    StageStatus,
)
from mos.storage import ObjectStore
from mos.templates import default_registry


# --- Stage execution config ---------------------------------------------

@dataclass(frozen=True)
class PipelineConfig:
    """Inputs the orchestrator needs but that are NOT part of the job record.

    These are effectively per-environment / per-tenant settings. In M11+ they
    become a richer per-job config carried on the Job record itself.
    """

    # Metal rate in INR/kg, keyed by alloy. Manual source for M10.
    metal_rates_inr_per_kg: dict[BrassAlloy, float]
    # INR -> USD FX rate.
    inr_to_usd: float
    # Yield override; if None, use rates.default_yield_pct from labor_rates.yaml.
    yield_pct: float | None = None
    # Optional freight inputs.
    freight: FreightInput | None = None
    # Render options. None disables rendering (stage marked SKIPPED).
    # If set but Blender isn't found at runtime, the stage is also SKIPPED
    # and the missing-Blender reason is recorded in the stage's error field —
    # rendering is not allowed to fail the job.
    render: RenderOptions | None = RenderOptions()


# --- Stage status helpers ------------------------------------------------

def _set_stage(
    stages: list[StageRecord],
    name: StageName,
    *,
    status: StageStatus,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error: str | None = None,
) -> list[StageRecord]:
    """Return a new list with the named stage replaced. Stages are frozen."""
    new = []
    for s in stages:
        if s.name == name:
            # Preserve started_at if already set; caller may override.
            new.append(
                StageRecord(
                    name=name,
                    status=status,
                    started_at=started_at if started_at is not None else s.started_at,
                    finished_at=finished_at,
                    error=error,
                )
            )
        else:
            new.append(s)
    return new


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Stage executors ----------------------------------------------------
#
# Each returns the updated ArtifactBundle with its stage's outputs added.
# Stages do not mutate Job directly — the orchestrator wraps them.


def _stage_cad(
    spec: DesignSpec,
    job_id: UUID,
    store: ObjectStore,
    bundle: ArtifactBundle,
):
    """Run CAD. Returns (updated bundle, GeometryMetrics).

    The metrics object includes finished_weight_g for the cost stage and
    bbox dimensions for the SOP stage's shop drawing.
    """
    with tempfile.TemporaryDirectory() as td:
        result = run_cad(spec, default_registry(), Path(td))
        if not result.report.passed:
            fails = [c for c in result.report.checks if c.status.value == "fail"]
            raise RuntimeError(
                "CAD stage: DFM report has FAIL checks: "
                + ", ".join(f"{c.rule_id.value}({c.message})" for c in fails)
            )
        step_key = f"jobs/{job_id}/cad/{spec.spec_id}.step"
        stl_key = f"jobs/{job_id}/cad/{spec.spec_id}.stl"
        step_uri = store.put_file(result.step_path, step_key)
        stl_uri = store.put_file(result.stl_path, stl_key)
        metrics = result.metrics

    return (
        bundle.model_copy(update={"step_uri": step_uri, "stl_uri": stl_uri}),
        metrics,
    )


def _stage_cost(
    spec: DesignSpec,
    job_id: UUID,
    finished_weight_g: float,
    config: PipelineConfig,
    store: ObjectStore,
    bundle: ArtifactBundle,
    cost_repo: CostSheetRepository,
):
    """Returns (bundle, cost_sheet) — sheet is forwarded to the SOP stage."""
    rates = load_cost_rates()
    yield_pct = config.yield_pct if config.yield_pct is not None else rates.default_yield_pct
    if not (0 < yield_pct <= 100):
        raise ValueError(f"yield_pct must be in (0, 100], got {yield_pct}")
    raw_weight_g = finished_weight_g / (yield_pct / 100.0)

    metal_rate = ManualMetalRateSource(config.metal_rates_inr_per_kg).fetch(
        spec.material.alloy
    )
    fx = ManualFxSource(config.inr_to_usd).fetch()

    sheet = compute_cost_sheet(
        spec=spec,
        raw_weight_g=raw_weight_g,
        finished_weight_g=finished_weight_g,
        rates=rates,
        metal_rate=metal_rate,
        fx=fx,
        freight=config.freight,
    )
    cost_repo.create(sheet)

    sheet_key = f"jobs/{job_id}/cost/{sheet.sheet_id}.json"
    sheet_uri = store.put_bytes(
        sheet.model_dump_json(indent=2).encode("utf-8"),
        sheet_key,
        content_type="application/json",
    )
    return (
        bundle.model_copy(update={"cost_sheet_json_uri": sheet_uri}),
        sheet,
    )


def _stage_bundle(
    job_id: UUID,
    store: ObjectStore,
    bundle: ArtifactBundle,
) -> ArtifactBundle:
    """Zip the artifacts we have and upload. Missing artifacts (e.g. SOP)
    are simply omitted from the zip."""
    artifact_uris: dict[str, str | None] = {
        "step": bundle.step_uri,
        "stl": bundle.stl_uri,
        "cost_sheet.json": bundle.cost_sheet_json_uri,
        "shop_drawing.pdf": bundle.shop_drawing_pdf_uri,
        "sop.pdf": bundle.sop_pdf_uri,
    }
    # Add render PNGs (zero or more).
    for i, png_uri in enumerate(bundle.render_png_uris):
        artifact_uris[f"render_{i}.png"] = png_uri
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, uri in artifact_uris.items():
            if uri is None:
                continue
            data = store.get_bytes(uri)
            # Preserve the original file extension.
            suffix = Path(name).suffix
            stem = Path(name).stem
            zf.writestr(f"{stem}{suffix}", data)
    buf.seek(0)
    bundle_key = f"jobs/{job_id}/bundle.zip"
    bundle_uri = store.put_bytes(
        buf.getvalue(), bundle_key, content_type="application/zip"
    )
    return bundle.model_copy(update={"bundle_zip_uri": bundle_uri})


def _stage_render(
    spec: DesignSpec,
    job_id: UUID,
    stl_uri: str | None,
    store: ObjectStore,
    bundle: ArtifactBundle,
    options: RenderOptions,
) -> tuple[ArtifactBundle, str | None]:
    """Run Blender render. Returns (bundle, skip_reason).

    skip_reason is None on success. If non-None, the stage should be marked
    SKIPPED rather than SUCCEEDED — the caller decides. Render failure must
    not fail the job (rendering is decorative; CAD/cost are the deliverables).
    """
    if stl_uri is None:
        return bundle, "no STL produced upstream; nothing to render"

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        stl_local = tdir / "input.stl"
        stl_local.write_bytes(store.get_bytes(stl_uri))
        png_local = tdir / "render.png"
        try:
            render_stl(stl_local, png_local, options=options)
        except BlenderNotFoundError as e:
            return bundle, f"Blender not available: {e}"
        except BlenderRenderError as e:
            return bundle, f"render failed: {e}"

        png_key = f"jobs/{job_id}/render/{spec.spec_id}.png"
        png_uri = store.put_file(png_local, png_key)

    return (
        bundle.model_copy(update={"render_png_uris": [png_uri]}),
        None,
    )


def _stage_sop(
    spec: DesignSpec,
    job_id: UUID,
    cost_sheet,  # CostSheet | None — typed loosely to avoid an import cycle
    geometry,    # GeometryMetrics
    bundle: ArtifactBundle,
    store: ObjectStore,
) -> tuple[ArtifactBundle, str | None]:
    """Generate shop drawing + SOP PDFs. Returns (bundle, skip_reason).

    Non-fatal — same contract as render. If PDF generation raises, mark the
    stage SKIPPED with the reason rather than failing the job.
    """
    from mos.sop import (
        ShopDrawingInputs,
        SopInputs,
        render_shop_drawing,
        render_sop,
    )

    drawing_number = f"DWG-{str(spec.spec_id)[:8]}-V1"
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        drawing_path = tdir / "shop_drawing.pdf"
        sop_path = tdir / "sop.pdf"
        try:
            render_shop_drawing(
                spec,
                ShopDrawingInputs(
                    drawing_number=drawing_number,
                    geometry=geometry,
                ),
                drawing_path,
            )
            render_sop(
                spec,
                SopInputs(
                    drawing_number=drawing_number,
                    cost_sheet=cost_sheet,
                ),
                sop_path,
            )
        except Exception as e:  # noqa: BLE001 — non-fatal stage
            return bundle, f"PDF generation failed: {type(e).__name__}: {e}"

        drawing_uri = store.put_file(
            drawing_path, f"jobs/{job_id}/sop/{spec.spec_id}.drawing.pdf",
        )
        sop_uri = store.put_file(
            sop_path, f"jobs/{job_id}/sop/{spec.spec_id}.sop.pdf",
        )

    return (
        bundle.model_copy(update={
            "shop_drawing_pdf_uri": drawing_uri,
            "sop_pdf_uri": sop_uri,
        }),
        None,
    )


# --- Orchestrator --------------------------------------------------------

class PipelineError(RuntimeError):
    """Wraps a stage failure. The orchestrator has already marked the job
    FAILED by the time this is raised."""

    def __init__(self, stage: StageName, underlying: Exception) -> None:
        super().__init__(f"pipeline failed at stage {stage.value}: {underlying}")
        self.stage = stage
        self.underlying = underlying


def run_pipeline(
    job_id: UUID,
    *,
    job_repo: JobRepository,
    spec_repo: DesignSpecRepository,
    cost_repo: CostSheetRepository,
    store: ObjectStore,
    config: PipelineConfig,
) -> Job:
    """Drive the job to completion. Returns the final Job record.

    Raises PipelineError if any stage fails. The job is persisted in FAILED
    state before the exception is raised.
    """
    job = job_repo.get(job_id)
    if job.status != JobStatus.QUEUED:
        raise ValueError(
            f"run_pipeline expects QUEUED job, got {job.status.value}"
        )
    if job.spec_id is None:
        raise ValueError("run_pipeline requires job.spec_id to be set")

    spec = spec_repo.get(job.spec_id)

    # Mark RUNNING upfront.
    stages = list(job.stages)
    job_repo.update(job.model_copy(update={"status": JobStatus.RUNNING, "stages": stages}))

    # Stages that are not yet implemented — mark SKIPPED up front so the
    # Job-level validators are happy when the job reaches COMPLETE.
    # RENDER and SOP are no longer here — they have their own
    # (possibly-skipped) branches in the loop below.
    for stage_name in (StageName.INTENT,):
        stages = _set_stage(stages, stage_name, status=StageStatus.SKIPPED)

    bundle = job.artifacts
    geometry = None  # GeometryMetrics from CAD stage
    cost_sheet = None  # CostSheet from COST stage; consumed by SOP

    for stage_name, fn in (
        (StageName.CAD, "cad"),
        (StageName.COST, "cost"),
        (StageName.RENDER, "render"),
        (StageName.SOP, "sop"),
        (StageName.BUNDLE, "bundle"),
    ):
        # Render is the only stage with a per-job opt-out (config.render=None
        # disables it). Mark SKIPPED and move on without RUNNING/started_at
        # so the stage record stays clean.
        if stage_name == StageName.RENDER and config.render is None:
            stages = _set_stage(
                stages, stage_name, status=StageStatus.SKIPPED,
                error="rendering disabled in PipelineConfig",
            )
            continue

        started = _now()
        stages = _set_stage(
            stages, stage_name, status=StageStatus.RUNNING, started_at=started
        )
        job = job.model_copy(update={"stages": stages, "artifacts": bundle})
        job_repo.update(job)

        try:
            if fn == "cad":
                bundle, geometry = _stage_cad(spec, job_id, store, bundle)
            elif fn == "cost":
                assert geometry is not None
                bundle, cost_sheet = _stage_cost(
                    spec, job_id, geometry.mass_g, config, store, bundle, cost_repo
                )
            elif fn == "render":
                # Non-fatal stage. If render produces a skip_reason, mark
                # SKIPPED instead of SUCCEEDED. Errors during render are
                # captured as skip_reasons by _stage_render itself.
                bundle, skip_reason = _stage_render(
                    spec, job_id, bundle.stl_uri, store, bundle, config.render
                )
                if skip_reason is not None:
                    stages = _set_stage(
                        stages, stage_name, status=StageStatus.SKIPPED,
                        finished_at=_now(), error=skip_reason,
                    )
                    continue  # don't fall through to SUCCEEDED below
            elif fn == "sop":
                # Non-fatal stage, same contract as render. PDF generation
                # failure marks SKIPPED rather than failing the job.
                assert geometry is not None
                bundle, skip_reason = _stage_sop(
                    spec, job_id, cost_sheet, geometry, bundle, store
                )
                if skip_reason is not None:
                    stages = _set_stage(
                        stages, stage_name, status=StageStatus.SKIPPED,
                        finished_at=_now(), error=skip_reason,
                    )
                    continue
            elif fn == "bundle":
                bundle = _stage_bundle(job_id, store, bundle)
            stages = _set_stage(
                stages,
                stage_name,
                status=StageStatus.SUCCEEDED,
                finished_at=_now(),
            )
        except Exception as e:  # noqa: BLE001 — we re-raise wrapped
            stages = _set_stage(
                stages,
                stage_name,
                status=StageStatus.FAILED,
                finished_at=_now(),
                error=f"{type(e).__name__}: {e}"[:2000],
            )
            job = job.model_copy(
                update={
                    "status": JobStatus.FAILED,
                    "stages": stages,
                    "artifacts": bundle,
                }
            )
            job_repo.update(job)
            raise PipelineError(stage_name, e) from e

    job = job.model_copy(
        update={
            "status": JobStatus.COMPLETE,
            "stages": stages,
            "artifacts": bundle,
        }
    )
    job_repo.update(job)
    return job
