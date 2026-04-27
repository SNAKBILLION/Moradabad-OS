"""Integration test: full POST /jobs path with brief-only input.

Uses a fake intent client (no Groq) but a real Postgres + InMemoryObjectStore.
Verifies the brief→spec→pipeline path end-to-end.
"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi.testclient import TestClient

from mos.api.app import (
    create_app,
    get_intent_client,
    get_session_factory,
    get_store,
)
from mos.db import (
    CostSheetRepository,
    DesignSpecRepository,
    JobRepository,
    LlmCallRepository,
)
from mos.intent.client import GroqResponse
from mos.schemas import (
    BrassAlloy,
    JobStatus,
)
from mos.storage import InMemoryObjectStore
from mos.worker.pipeline import PipelineConfig, run_pipeline


class _FakeGroqClient:
    model = "fake-llama-3.1-70b"

    def __init__(self, json_payload: dict) -> None:
        self._payload = json_payload

    def chat_json(self, *, system, user, temperature=0.0):
        return GroqResponse(
            content=json.dumps(self._payload),
            raw_json={"choices": []},
            model=self.model,
        )


def _valid_spec_payload(brief_placeholder: str = "00000000-0000-0000-0000-000000000000") -> dict:
    return {
        "schema_version": "1.0",
        "brief_id": brief_placeholder,
        "product_family": "candle_holder",
        "template_id": "candle_holder_classic_v1",
        "dimensions": {
            "base_diameter": {"value": 80.0, "unit": "mm"},
            "neck_diameter": {"value": 50.0, "unit": "mm"},
            "height": {"value": 130.0, "unit": "mm"},
            "wall_thickness": {"value": 4.0, "unit": "mm"},
        },
        "material": {
            "alloy": "brass_70_30",
            "casting_method": "sand",
            "density_g_cm3": 8.53,
            "min_wall_mm": 3.0,
        },
        "finish": {
            "polish": "satin",
            "plating": "none",
            "lacquer": False,
            "patina": None,
        },
        "motif_refs": [],
        "quantity": 100,
        "target_unit_cost": None,
        "buyer_notes": "test",
    }


def _pipeline_config() -> PipelineConfig:
    return PipelineConfig(
        metal_rates_inr_per_kg={BrassAlloy.BRASS_70_30: 720.0},
        inr_to_usd=0.012,
    )


class TestBriefOnlyJob:
    def test_post_with_brief_runs_intent_then_pipeline(self, session_factory):
        app = create_app()
        from mos.api.app import verify_key
        app.dependency_overrides[verify_key] = lambda: None
        store = InMemoryObjectStore()

        # Override deps: real DB factory, in-memory store, fake intent client,
        # synchronous enqueue.
        app.dependency_overrides[get_session_factory] = lambda: session_factory
        app.dependency_overrides[get_store] = lambda: store
        app.dependency_overrides[get_intent_client] = lambda: _FakeGroqClient(
            _valid_spec_payload()
        )

        import mos.api.app as api_module

        original_enqueue = api_module.enqueue_pipeline

        def _sync_enqueue(job_id):
            run_pipeline(
                job_id,
                job_repo=JobRepository(session_factory),
                spec_repo=DesignSpecRepository(session_factory),
                cost_repo=CostSheetRepository(session_factory),
                store=store,
                config=_pipeline_config(),
            )

        api_module.enqueue_pipeline = _sync_enqueue
        try:
            client = TestClient(app)
            resp = client.post(
                "/jobs",
                json={
                    "owner_id": str(uuid4()),
                    "brief_text": "8cm hollow brass candle holder, satin finish",
                    # design_spec omitted -> intent layer runs
                },
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["status"] == JobStatus.COMPLETE.value
            assert body["artifact_urls"]["bundle_zip"] is not None

            # llm_calls must have one row for this brief.
            log = LlmCallRepository(session_factory)
            # We don't have brief_id directly, but we can look it up via job
            jobs = JobRepository(session_factory)
            job = jobs.get(body["job_id"])
            assert log.count_for_brief(job.brief_id) == 1
        finally:
            api_module.enqueue_pipeline = original_enqueue
            app.dependency_overrides.clear()

    def test_post_with_brief_when_intent_fails_goes_to_review(
        self, session_factory
    ):
        app = create_app()
        from mos.api.app import verify_key
        app.dependency_overrides[verify_key] = lambda: None
        store = InMemoryObjectStore()

        # Fake client returns garbage every time -> intent gives up, job
        # should land in AWAITING_REVIEW with no pipeline run.
        class _BadClient:
            model = "fake"

            def chat_json(self, *, system, user, temperature=0.0):
                return GroqResponse(
                    content="not even json",
                    raw_json={},
                    model=self.model,
                )

        app.dependency_overrides[get_session_factory] = lambda: session_factory
        app.dependency_overrides[get_store] = lambda: store
        app.dependency_overrides[get_intent_client] = lambda: _BadClient()

        import mos.api.app as api_module

        # If pipeline gets enqueued, fail loudly.
        api_module.enqueue_pipeline = lambda job_id: pytest_fail(  # type: ignore[name-defined]
            f"enqueue should not be called; job_id={job_id}"
        )

        try:
            client = TestClient(app)
            resp = client.post(
                "/jobs",
                json={
                    "owner_id": str(uuid4()),
                    "brief_text": "anything",
                },
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["status"] == JobStatus.AWAITING_REVIEW.value
            assert body["intent_reason"] is not None
            assert body["artifact_urls"]["bundle_zip"] is None
        finally:
            app.dependency_overrides.clear()


# Helper for the second test — pytest needs to be importable for the assertion
import pytest  # noqa: E402

pytest_fail = pytest.fail
