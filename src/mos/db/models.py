"""ORM models for Phase 1 persistence.

Design choices:

1. Separate from Pydantic schemas. ORM models enforce STORAGE invariants
   (FKs, indexes, not-null); Pydantic enforces DOMAIN invariants. Repository
   converts between them.

2. Free-form nested structures (cost line items, feedback payloads, DFM
   check lists, artifact URIs) are stored as JSONB of the Pydantic JSON.
   Queryable scalars (status, owner_id, timestamps, FK columns) are real
   SQL columns. Hybrid by design.

3. All timestamps are timezone-aware UTC. No naive datetimes anywhere.

4. Table names are plural snake_case. Columns are snake_case.

5. Primary keys are UUIDs generated application-side (matching Pydantic
   defaults). Using `uuid.uuid4` via default=; database-side `gen_random_uuid`
   would require the pgcrypto extension and isn't worth it here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base for all ORM models. Do NOT add columns here — explicit is better."""


# --- Briefs --------------------------------------------------------------

class BriefRow(Base):
    __tablename__ = "briefs"

    brief_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (Index("ix_briefs_owner_id", "owner_id"),)


# --- Design specs --------------------------------------------------------

class DesignSpecRow(Base):
    """Stores the full DesignSpec as JSONB; duplicates a handful of columns
    for queryability (product_family, template_id, quantity)."""

    __tablename__ = "design_specs"

    spec_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    brief_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("briefs.brief_id", ondelete="RESTRICT"),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    product_family: Mapped[str] = mapped_column(String(64), nullable=False)
    template_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_design_specs_brief_id", "brief_id"),
        Index("ix_design_specs_template_id", "template_id"),
    )


# --- Jobs ----------------------------------------------------------------

class JobRow(Base):
    """Orchestration record. Stages + artifacts + snapshot live as JSONB
    because they're written atomically and never queried by their internals."""

    __tablename__ = "jobs"

    job_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    owner_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    brief_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("briefs.brief_id", ondelete="RESTRICT"),
        nullable=False,
    )
    spec_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("design_specs.spec_id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    # JSONB blobs — written as a unit; internal structure validated by
    # Pydantic on the way in and out.
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    __table_args__ = (
        Index("ix_jobs_owner_id", "owner_id"),
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_created_at", "created_at"),
    )


# --- Cost sheets ---------------------------------------------------------

class CostSheetRow(Base):
    __tablename__ = "cost_sheets"

    sheet_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    spec_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("design_specs.spec_id", ondelete="RESTRICT"),
        nullable=False,
    )
    ex_factory_inr: Mapped[float] = mapped_column(Float, nullable=False)
    fob_moradabad_inr: Mapped[float] = mapped_column(Float, nullable=False)
    fob_moradabad_usd: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (Index("ix_cost_sheets_spec_id", "spec_id"),)


# --- Feedback ------------------------------------------------------------

class FeedbackRow(Base):
    """Append-only. No UPDATEs, no DELETEs — enforce at application layer."""

    __tablename__ = "feedback"

    feedback_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    job_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("jobs.job_id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_role: Mapped[str] = mapped_column(String(32), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    notes_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_feedback_job_id", "job_id"),
        Index("ix_feedback_type", "feedback_type"),
    )


# --- External rate snapshots --------------------------------------------

class MetalRateRow(Base):
    """Daily metal rate history. Unique on (metal, rate_date) prevents
    accidental double-insertion."""

    __tablename__ = "metal_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metal: Mapped[str] = mapped_column(String(32), nullable=False)  # "brass_70_30"
    rate_per_kg_inr: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    rate_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ux_metal_rates_metal_date", "metal", "rate_date", unique=True),
    )


class FxRateRow(Base):
    __tablename__ = "fx_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(16), nullable=False)  # "INR/USD"
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    rate_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ux_fx_rates_pair_date", "pair", "rate_date", unique=True),
    )


# --- Template registry ---------------------------------------------------

class TemplateRow(Base):
    """Registry of available parametric templates. The actual CadQuery code
    lives in src/mos/templates/brass/*.py; this row is metadata only."""

    __tablename__ = "templates"

    template_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    product_family: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    param_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    regions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)  # motif placement regions
    active: Mapped[bool] = mapped_column(
        default=True, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (Index("ix_templates_product_family", "product_family"),)


# --- LLM calls (intent-layer audit log) ---------------------------------

class LlmCallRow(Base):
    """One row per LLM request attempt. Append-only."""

    __tablename__ = "llm_calls"

    call_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    brief_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("briefs.brief_id", ondelete="RESTRICT"),
        nullable=False,
    )
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    succeeded: Mapped[bool] = mapped_column(nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_llm_calls_brief_id", "brief_id"),
        Index("ix_llm_calls_created_at", "created_at"),
        Index("ix_llm_calls_prompt_hash", "prompt_hash"),
    )
