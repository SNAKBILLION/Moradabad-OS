"""End-to-end integration test for the pipeline.

The milestone's binary success criterion: POST /jobs → GET /jobs/{id} →
bundle URI available. This test hits a real Postgres (skipped without it),
an in-memory object store (no MinIO needed for unit logic), and runs the
orchestrator synchronously (no Redis needed).

A separate Celery+Redis+MinIO full-stack test is out of scope for this
sandbox; run it manually with `docker compose up -d && celery -A mos.worker.app
worker` on your machine.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient

from mos.api.app import (
    create_app,
    enqueue_pipeline,
    get_session_factory,
    get_store,
)
from mos.db import CostSheetRepository, DesignSpecRepository, JobRepository
from mos.schemas import (
    BrassAlloy,
    CastingMethod,
    DesignSpec,
    FinishSpec,
    JobStatus,
    MaterialSpec,
    Measurement,
    Plating,
    PolishFinish,
    ProductFamily,
)
from mos.storage import InMemoryObjectStore
from mos.worker.pipeline import PipelineConfig, run_pipeline


def _make_spec() -> DesignSpec:
    return DesignSpec(
        brief_id=uuid4(),
        product_family=ProductFamily.CANDLE_HOLDER,
        template_id="candle_holder_classic_v1",
        dimensions={
            "base_diameter": Measurement(value=80.0, unit="mm"),
            "neck_diameter": Measurement(value=40.0, unit="mm"),
            "height": Measurement(value=120.0, unit="mm"),
            "wall_thickness": Measurement(value=3.5, unit="mm"),
        },
        material=MaterialSpec.for_alloy(
            BrassAlloy.BRASS_70_30, CastingMethod.SAND
        ),
        finish=FinishSpec(polish=PolishFinish.SATIN, plating=Plating.NICKEL),
        motif_refs=[],
        quantity=100,
        buyer_notes="",
    )


def _pipeline_config() -> PipelineConfig:
    return PipelineConfig(
        metal_rates_inr_per_kg={BrassAlloy.BRASS_70_30: 720.0},
        inr_to_usd=0.012,
    )


class TestPipelineEndToEnd:
    def test_orchestrator_runs_to_completion(
        self, session_factory
    ):
        """Orchestrator directly (no FastAPI). Proves stages wire correctly."""
        from mos.db.repository import BriefRepository

        briefs = BriefRepository(session_factory)
        specs = DesignSpecRepository(session_factory)
        jobs = JobRepository(session_factory)
        cost_repo = CostSheetRepository(session_factory)
        store = InMemoryObjectStore()

        spec = _make_spec()
        owner = uuid4()
        briefs.create_with_id(
            brief_id=spec.brief_id, owner_id=owner, raw_text="test brief"
        )
        specs.create(spec)

        from mos.schemas import (
            ArtifactBundle,
            Job,
            PipelineSnapshot,
            SCHEMA_VERSION,
            StageName,
            StageRecord,
            StageStatus,
        )

        snapshot = PipelineSnapshot(
            schemas_version=SCHEMA_VERSION,
            template_id=spec.template_id,
            template_version="v1.0",
            dfm_rules_version="runtime",
            cost_engine_version="runtime",
            sop_template_version="not-implemented",
            llm_model="not-implemented",
            random_seed=0,
        )
        job = Job(
            owner_id=owner,
            brief_id=spec.brief_id,
            spec_id=spec.spec_id,
            status=JobStatus.QUEUED,
            stages=[
                StageRecord(name=s, status=StageStatus.PENDING)
                for s in StageName
            ],
            artifacts=ArtifactBundle(),
            snapshot=snapshot,
        )
        jobs.create(job)

        final = run_pipeline(
            job.job_id,
            job_repo=jobs,
            spec_repo=specs,
            cost_repo=cost_repo,
            store=store,
            config=_pipeline_config(),
        )
        assert final.status == JobStatus.COMPLETE
        assert final.artifacts.step_uri is not None
        assert final.artifacts.stl_uri is not None
        assert final.artifacts.cost_sheet_json_uri is not None
        assert final.artifacts.bundle_zip_uri is not None

        # Cost sheet was persisted and is retrievable.
        sheet = cost_repo.get_by_spec(spec.spec_id)
        assert sheet is not None
        assert sheet.totals.ex_factory_inr > 0

        # Bundle zip contains the expected entries.
        zip_bytes = store.get_bytes(final.artifacts.bundle_zip_uri)
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            names = set(zf.namelist())
        assert "step" in names
        assert "stl" in names
        assert "cost_sheet.json" in names

    def test_api_post_then_get(self, session_factory):
        """Full API round trip using TestClient. Pipeline runs synchronously
        via the enqueue override."""
        app = create_app()
        from mos.api.app import verify_key
        app.dependency_overrides[verify_key] = lambda: None
           
        store = InMemoryObjectStore()
        ran_jobs: list[str] = []

        def _sync_enqueue(job_id):
            # Run the pipeline inline — no Celery, no Redis.
            ran_jobs.append(str(job_id))
            run_pipeline(
                job_id,
                job_repo=JobRepository(session_factory),
                spec_repo=DesignSpecRepository(session_factory),
                cost_repo=CostSheetRepository(session_factory),
                store=store,
                config=_pipeline_config(),
            )

        app.dependency_overrides[get_session_factory] = lambda: session_factory
        app.dependency_overrides[get_store] = lambda: store
        # Monkey-patch the enqueue hook. dependency_overrides doesn't reach
        # module-level functions, so we override at module scope.
        import mos.api.app as api_module

        original_enqueue = api_module.enqueue_pipeline
        api_module.enqueue_pipeline = _sync_enqueue
        try:
            client = TestClient(app)
            resp = client.get("/healthz")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

            owner = uuid4()
            spec = _make_spec()
            create_resp = client.post(
                "/jobs",
                json={
                    "owner_id": str(owner),
                    "brief_text": "antique brass candle holder",
                    "design_spec": spec.model_dump(mode="json"),
                },
            )
            assert create_resp.status_code == 201, create_resp.text
            body = create_resp.json()
            job_id = body["job_id"]
            assert len(ran_jobs) == 1 and ran_jobs[0] == job_id
            # Status should already be COMPLETE because enqueue ran sync.
            assert body["status"] == JobStatus.COMPLETE.value

            get_resp = client.get(f"/jobs/{job_id}")
            assert get_resp.status_code == 200
            gbody = get_resp.json()
            assert gbody["status"] == JobStatus.COMPLETE.value
            urls = gbody["artifact_urls"]
            assert urls["step"] is not None
            assert urls["stl"] is not None
            assert urls["cost_sheet_json"] is not None
            assert urls["bundle_zip"] is not None

            # Unknown job id => 404.
            assert client.get(f"/jobs/{uuid4()}").status_code == 404
        finally:
            api_module.enqueue_pipeline = original_enqueue
            app.dependency_overrides.clear()
