"""Integration tests for the feedback API.

The milestone success criterion: all 5 FeedbackPayload types post-and-retrieve
round-trip. We hit a real Postgres + the in-memory storage fake.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mos.api.app import (
    create_app,
    get_session_factory,
    get_store,
)
from mos.db import (
    BriefRepository,
    FeedbackRepository,
    JobRepository,
)
from mos.schemas import (
    ArtifactBundle,
    Job,
    JobStatus,
    LineItemCode,
    PipelineSnapshot,
    SCHEMA_VERSION,
    StageName,
    StageRecord,
    StageStatus,
    UserRole,
)
from mos.schemas.manufacturability import CheckRule
from mos.storage import InMemoryObjectStore


def _seed_job(session_factory, owner_id=None):
    """Insert a brief + queued job so feedback has a valid FK target.

    Returns (job_id, owner_id). The job is intentionally minimal — feedback
    routes don't read job state, only job_id existence.
    """
    owner = owner_id or uuid4()
    briefs = BriefRepository(session_factory)
    jobs = JobRepository(session_factory)
    brief_id = briefs.create(owner, "feedback test brief")

    snapshot = PipelineSnapshot(
        schemas_version=SCHEMA_VERSION,
        template_id=None,
        template_version=None,
        dfm_rules_version="test",
        cost_engine_version="test",
        sop_template_version="test",
        llm_model="test",
        random_seed=0,
    )
    job = Job(
        owner_id=owner,
        brief_id=brief_id,
        spec_id=None,
        status=JobStatus.QUEUED,
        stages=[
            StageRecord(name=s, status=StageStatus.PENDING) for s in StageName
        ],
        artifacts=ArtifactBundle(),
        snapshot=snapshot,
    )
    jobs.create(job)
    return job.job_id, owner


@pytest.fixture
def client(session_factory):
    """API client with overridden DB factory and an in-memory store. No
    pipeline runs in feedback tests — we override get_store with a no-op
    that won't be called."""
    app = create_app()
    from mos.api.app import verify_key
    app.dependency_overrides[verify_key] = 
    lambda: None
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_store] = lambda: InMemoryObjectStore()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# Five payload bodies covering every FeedbackType. Wire-format dicts as the
# client would actually send them.
_PAYLOAD_CASES = [
    pytest.param(
        {
            "type": "cost_actual",
            "line_item_code": LineItemCode.CASTING_LABOR.value,
            "actual_inr": 142.50,
        },
        id="cost_actual",
    ),
    pytest.param(
        {"type": "cannot_manufacture", "reason_code": "undercut"},
        id="cannot_manufacture",
    ),
    pytest.param(
        {
            "type": "dfm_violation_observed",
            "rule_id": CheckRule.MIN_WALL_THICKNESS.value,
            "observed_value": 2.4,
        },
        id="dfm_violation_observed",
    ),
    pytest.param(
        {
            "type": "finish_defect",
            "defect_code": "pitting",
            "severity": "major",
        },
        id="finish_defect",
    ),
    pytest.param(
        {
            "type": "time_actual",
            "process": "polishing",
            "actual_minutes": 18.0,
        },
        id="time_actual",
    ),
]


class TestFeedbackRoundTrip:
    @pytest.mark.parametrize("payload", _PAYLOAD_CASES)
    def test_post_then_get_each_payload_type(
        self, client, session_factory, payload
    ):
        job_id, _ = _seed_job(session_factory)

        # POST
        post = client.post(
            f"/jobs/{job_id}/feedback",
            json={
                "user_role": UserRole.SUPERVISOR.value,
                "payload": payload,
                "notes_text": "round-trip note",
            },
        )
        assert post.status_code == 201, post.text
        body = post.json()
        feedback_id = body["feedback_id"]
        assert body["job_id"] == str(job_id)
        assert body["payload"]["type"] == payload["type"]
        assert body["notes_text"] == "round-trip note"

        # GET single
        got = client.get(f"/feedback/{feedback_id}")
        assert got.status_code == 200
        assert got.json()["feedback_id"] == feedback_id
        assert got.json()["payload"] == body["payload"]

        # GET list — must include this record
        listed = client.get(f"/jobs/{job_id}/feedback")
        assert listed.status_code == 200
        ids = {r["feedback_id"] for r in listed.json()}
        assert feedback_id in ids


class TestFeedbackErrorPaths:
    def test_post_to_unknown_job_returns_404(self, client):
        resp = client.post(
            f"/jobs/{uuid4()}/feedback",
            json={
                "user_role": UserRole.QC.value,
                "payload": {
                    "type": "cannot_manufacture",
                    "reason_code": "test",
                },
            },
        )
        assert resp.status_code == 404

    def test_get_unknown_feedback_returns_404(self, client):
        resp = client.get(f"/feedback/{uuid4()}")
        assert resp.status_code == 404

    def test_list_for_unknown_job_is_empty_list_not_404(
        self, client, session_factory
    ):
        # Reading feedback for a job that doesn't exist should return [],
        # not 404 — it's a query, not an action that requires the job.
        resp = client.get(f"/jobs/{uuid4()}/feedback")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_bad_payload_discriminator_returns_422(self, client, session_factory):
        job_id, _ = _seed_job(session_factory)
        resp = client.post(
            f"/jobs/{job_id}/feedback",
            json={
                "user_role": UserRole.QC.value,
                "payload": {
                    # missing "type" discriminator
                    "actual_minutes": 5.0,
                },
            },
        )
        assert resp.status_code == 422

    def test_wrong_severity_enum_returns_422(self, client, session_factory):
        job_id, _ = _seed_job(session_factory)
        resp = client.post(
            f"/jobs/{job_id}/feedback",
            json={
                "user_role": UserRole.QC.value,
                "payload": {
                    "type": "finish_defect",
                    "defect_code": "scratch",
                    "severity": "catastrophic",  # not in {minor, major, reject}
                },
            },
        )
        assert resp.status_code == 422

    def test_list_limit_out_of_range_returns_422(
        self, client, session_factory
    ):
        job_id, _ = _seed_job(session_factory)
        resp = client.get(f"/jobs/{job_id}/feedback?limit=99999")
        assert resp.status_code == 422


class TestFeedbackOrdering:
    def test_list_returns_oldest_first(self, client, session_factory):
        job_id, _ = _seed_job(session_factory)
        for i in range(3):
            r = client.post(
                f"/jobs/{job_id}/feedback",
                json={
                    "user_role": UserRole.SUPERVISOR.value,
                    "payload": {
                        "type": "time_actual",
                        "process": f"step_{i}",
                        "actual_minutes": float(i + 1),
                    },
                },
            )
            assert r.status_code == 201
        listed = client.get(f"/jobs/{job_id}/feedback").json()
        assert len(listed) == 3
        # created_at ascending
        timestamps = [r["created_at"] for r in listed]
        assert timestamps == sorted(timestamps)
