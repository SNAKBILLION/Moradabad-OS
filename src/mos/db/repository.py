"""Repository layer for jobs and briefs.

The repository is the *only* place Pydantic models and ORM models meet.
Callers pass and receive Pydantic models; the ORM is an implementation detail.

No raw SQL, no lazy-loading surprises, no session passed in — the repository
owns a session factory and manages its own transactions via session_scope.
Tests can inject a factory bound to a transactional test session.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mos.db.models import BriefRow, CostSheetRow, DesignSpecRow, JobRow
from mos.db.session import session_scope
from mos.schemas import CostSheet, DesignSpec, Job, JobStatus


# --- Brief ----------------------------------------------------------------

class BriefRepository:
    """Minimal — briefs are referenced by jobs but don't have their own
    Pydantic type in Phase 1. We store only what's needed to satisfy the FK."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, owner_id: UUID, raw_text: str) -> UUID:
        with session_scope(self._session_factory) as s:
            row = BriefRow(owner_id=owner_id, raw_text=raw_text)
            s.add(row)
            s.flush()
            return row.brief_id

    def create_with_id(
        self, *, brief_id: UUID, owner_id: UUID, raw_text: str
    ) -> None:
        """Insert a brief with an externally-chosen id. Used by the API when
        the DesignSpec already carries a brief_id that must match."""
        with session_scope(self._session_factory) as s:
            s.add(
                BriefRow(
                    brief_id=brief_id, owner_id=owner_id, raw_text=raw_text
                )
            )


# --- Jobs -----------------------------------------------------------------

def _job_to_row(job: Job) -> JobRow:
    """Convert Pydantic Job -> ORM JobRow. Pure function, easy to test."""
    # Pydantic models serialize cleanly to dicts with mode="json" (enums,
    # UUIDs, datetimes all become JSON-safe). We store them that way so
    # JSONB round-trips are lossless.
    return JobRow(
        job_id=job.job_id,
        owner_id=job.owner_id,
        brief_id=job.brief_id,
        spec_id=job.spec_id,
        status=job.status.value,
        stages=[s.model_dump(mode="json") for s in job.stages],
        artifacts=job.artifacts.model_dump(mode="json"),
        snapshot=job.snapshot.model_dump(mode="json"),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _row_to_job(row: JobRow) -> Job:
    """Convert ORM JobRow -> Pydantic Job. Re-validates on reconstruction —
    if the DB got out of sync with the contract, we want to know immediately."""
    return Job.model_validate(
        {
            "job_id": row.job_id,
            "owner_id": row.owner_id,
            "brief_id": row.brief_id,
            "spec_id": row.spec_id,
            "status": row.status,
            "stages": row.stages,
            "artifacts": row.artifacts,
            "snapshot": row.snapshot,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


class JobNotFoundError(LookupError):
    """Raised by JobRepository.get when a job_id doesn't exist."""


class JobRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, job: Job) -> None:
        """Insert a new job. Raises IntegrityError if job_id already exists."""
        with session_scope(self._session_factory) as s:
            s.add(_job_to_row(job))

    def get(self, job_id: UUID) -> Job:
        with session_scope(self._session_factory) as s:
            row = s.get(JobRow, job_id)
            if row is None:
                raise JobNotFoundError(str(job_id))
            return _row_to_job(row)

    def list_for_owner(
        self,
        owner_id: UUID,
        *,
        status: JobStatus | None = None,
        limit: int = 50,
    ) -> list[Job]:
        """Most-recent-first. Phase 1 has no real pagination — cursor-based
        listing lands when the UI needs it."""
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        with session_scope(self._session_factory) as s:
            stmt = select(JobRow).where(JobRow.owner_id == owner_id)
            if status is not None:
                stmt = stmt.where(JobRow.status == status.value)
            stmt = stmt.order_by(JobRow.created_at.desc()).limit(limit)
            rows = s.execute(stmt).scalars().all()
            return [_row_to_job(r) for r in rows]

    def update(self, job: Job) -> None:
        """Replace an existing job's mutable fields (status, stages,
        artifacts, spec_id) in-place. Immutable fields (job_id, owner_id,
        brief_id, snapshot, created_at) are not changed. Raises if the job
        does not exist.
        """
        from datetime import datetime, timezone

        with session_scope(self._session_factory) as s:
            row = s.get(JobRow, job.job_id)
            if row is None:
                raise JobNotFoundError(str(job.job_id))
            row.status = job.status.value
            row.spec_id = job.spec_id
            row.stages = [st.model_dump(mode="json") for st in job.stages]
            row.artifacts = job.artifacts.model_dump(mode="json")
            row.updated_at = datetime.now(timezone.utc)


# --- Design spec ---------------------------------------------------------

class DesignSpecNotFoundError(LookupError):
    pass


class DesignSpecRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, spec: DesignSpec) -> None:
        """Insert the spec. Duplicating a spec_id raises IntegrityError."""
        with session_scope(self._session_factory) as s:
            s.add(
                DesignSpecRow(
                    spec_id=spec.spec_id,
                    brief_id=spec.brief_id,
                    schema_version=spec.schema_version,
                    product_family=spec.product_family.value,
                    template_id=spec.template_id,
                    quantity=spec.quantity,
                    payload=spec.model_dump(mode="json"),
                )
            )

    def get(self, spec_id: UUID) -> DesignSpec:
        with session_scope(self._session_factory) as s:
            row = s.get(DesignSpecRow, spec_id)
            if row is None:
                raise DesignSpecNotFoundError(str(spec_id))
            return DesignSpec.model_validate(row.payload)


# --- Cost sheet ----------------------------------------------------------

class CostSheetRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, sheet: CostSheet) -> None:
        with session_scope(self._session_factory) as s:
            s.add(
                CostSheetRow(
                    sheet_id=sheet.sheet_id,
                    spec_id=sheet.spec_id,
                    ex_factory_inr=sheet.totals.ex_factory_inr,
                    fob_moradabad_inr=sheet.totals.fob_moradabad_inr,
                    fob_moradabad_usd=sheet.totals.fob_moradabad_usd,
                    payload=sheet.model_dump(mode="json"),
                    generated_at=sheet.generated_at,
                )
            )

    def get_by_spec(self, spec_id: UUID) -> CostSheet | None:
        with session_scope(self._session_factory) as s:
            stmt = (
                select(CostSheetRow)
                .where(CostSheetRow.spec_id == spec_id)
                .order_by(CostSheetRow.generated_at.desc())
                .limit(1)
            )
            row = s.execute(stmt).scalars().first()
            if row is None:
                return None
            return CostSheet.model_validate(row.payload)


# --- LLM call log --------------------------------------------------------

class LlmCallRepository:
    """Append-only sink for LLM request/response records.

    Structurally satisfies the mos.intent.pipeline.LlmCallSink protocol so it
    can be injected wherever a sink is expected.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(self, call) -> None:  # LlmCallRecord — duck-typed to avoid cycle
        from mos.db.models import LlmCallRow

        with session_scope(self._session_factory) as s:
            s.add(
                LlmCallRow(
                    call_id=call.call_id,
                    brief_id=call.brief_id,
                    prompt_version=call.prompt_version,
                    prompt_hash=call.prompt_hash,
                    model=call.model,
                    attempt=call.attempt,
                    succeeded=call.succeeded,
                    error=call.error,
                    system_prompt=call.system_prompt,
                    user_prompt=call.user_prompt,
                    raw_response=call.raw_response,
                    created_at=call.created_at,
                )
            )

    def count_for_brief(self, brief_id: UUID) -> int:
        from mos.db.models import LlmCallRow

        with session_scope(self._session_factory) as s:
            stmt = select(LlmCallRow).where(LlmCallRow.brief_id == brief_id)
            return len(s.execute(stmt).scalars().all())


# --- Feedback ------------------------------------------------------------

class FeedbackNotFoundError(LookupError):
    """Raised when a feedback_id doesn't exist."""


def _feedback_to_row(record):
    """Pydantic FeedbackRecord -> ORM FeedbackRow.

    Duck-typed to avoid an import cycle with mos.schemas at module level —
    the schema module is large and only the FeedbackRow needs the import,
    which is local to repository methods.
    """
    from mos.db.models import FeedbackRow

    return FeedbackRow(
        feedback_id=record.feedback_id,
        job_id=record.job_id,
        user_role=record.user_role.value,
        feedback_type=record.payload.type.value,
        payload=record.payload.model_dump(mode="json"),
        notes_text=record.notes_text,
        created_at=record.created_at,
    )


def _row_to_feedback(row):
    """ORM FeedbackRow -> Pydantic FeedbackRecord."""
    from mos.schemas import FeedbackRecord

    return FeedbackRecord.model_validate(
        {
            "feedback_id": row.feedback_id,
            "job_id": row.job_id,
            "user_role": row.user_role,
            "payload": row.payload,
            "notes_text": row.notes_text,
            "created_at": row.created_at,
        }
    )


class FeedbackRepository:
    """Feedback storage. Append-only by convention — no update/delete methods.

    The schema's FK from feedback.job_id -> jobs.job_id (RESTRICT) prevents
    feedback from being orphaned if a job is deleted; the repository does
    not check job existence itself, relying on the FK to fail loudly.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, record) -> None:  # FeedbackRecord — duck-typed
        with session_scope(self._session_factory) as s:
            s.add(_feedback_to_row(record))

    def get(self, feedback_id: UUID):
        from mos.db.models import FeedbackRow

        with session_scope(self._session_factory) as s:
            row = s.get(FeedbackRow, feedback_id)
            if row is None:
                raise FeedbackNotFoundError(str(feedback_id))
            return _row_to_feedback(row)

    def list_for_job(self, job_id: UUID, *, limit: int = 100) -> list:
        """Oldest-first. Feedback is read in chronological order so a
        reviewer can see the sequence of events on a job."""
        from mos.db.models import FeedbackRow

        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with session_scope(self._session_factory) as s:
            stmt = (
                select(FeedbackRow)
                .where(FeedbackRow.job_id == job_id)
                .order_by(FeedbackRow.created_at.asc())
                .limit(limit)
            )
            rows = s.execute(stmt).scalars().all()
            return [_row_to_feedback(r) for r in rows]


# --- Metal rate cache ----------------------------------------------------

class MetalRateRepository:
    """Append-only(ish) cache for metal rate snapshots.

    Append-only by usage convention — we never UPDATE rows, only INSERT.
    The unique index on (metal, rate_date) prevents accidental duplicates
    for the same calendar day; the repo's ``upsert_for_today`` handles the
    natural "fetched twice today" case by ignoring the second insert.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def latest(self, metal: str):
        """Most recent cached rate for a metal, or None."""
        from mos.db.models import MetalRateRow

        with session_scope(self._session_factory) as s:
            stmt = (
                select(MetalRateRow)
                .where(MetalRateRow.metal == metal)
                .order_by(MetalRateRow.rate_date.desc())
                .limit(1)
            )
            row = s.execute(stmt).scalars().first()
            return row

    def upsert_for_date(
        self,
        *,
        metal: str,
        rate_per_kg_inr: float,
        source: str,
        rate_date: datetime,
    ) -> None:
        """Insert a rate. If a row already exists for this (metal, rate_date),
        do nothing — the unique index would otherwise raise IntegrityError.

        Uses Postgres ON CONFLICT for atomic idempotency rather than a
        check-then-insert race.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from mos.db.models import MetalRateRow

        with session_scope(self._session_factory) as s:
            stmt = (
                pg_insert(MetalRateRow)
                .values(
                    metal=metal,
                    rate_per_kg_inr=rate_per_kg_inr,
                    source=source,
                    rate_date=rate_date,
                )
                .on_conflict_do_nothing(
                    index_elements=["metal", "rate_date"]
                )
            )
            s.execute(stmt)
