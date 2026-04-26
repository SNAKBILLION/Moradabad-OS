"""initial schema

Revision ID: 48762f8fd95a
Revises:
Create Date: 2026-04-24

Creates all Phase 1 tables. Enables the pgvector extension even though no
column uses it yet — Phase 2 similarity search will land without requiring
a separate migration that needs DB admin rights.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "48762f8fd95a"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extensions. pgvector is currently unused but reserved for Phase 2.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "briefs",
        sa.Column("brief_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_briefs_owner_id", "briefs", ["owner_id"])

    op.create_table(
        "design_specs",
        sa.Column("spec_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "brief_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("briefs.brief_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("product_family", sa.String(64), nullable=False),
        sa.Column("template_id", sa.String(128), nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_design_specs_brief_id", "design_specs", ["brief_id"])
    op.create_index(
        "ix_design_specs_template_id", "design_specs", ["template_id"]
    )

    op.create_table(
        "jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "brief_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("briefs.brief_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "spec_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("design_specs.spec_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("stages", postgresql.JSONB, nullable=False),
        sa.Column("artifacts", postgresql.JSONB, nullable=False),
        sa.Column("snapshot", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_jobs_owner_id", "jobs", ["owner_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])

    op.create_table(
        "cost_sheets",
        sa.Column("sheet_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "spec_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("design_specs.spec_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ex_factory_inr", sa.Float, nullable=False),
        sa.Column("fob_moradabad_inr", sa.Float, nullable=False),
        sa.Column("fob_moradabad_usd", sa.Float, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_cost_sheets_spec_id", "cost_sheets", ["spec_id"])

    op.create_table(
        "feedback",
        sa.Column(
            "feedback_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.job_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("user_role", sa.String(32), nullable=False),
        sa.Column("feedback_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "notes_text", sa.Text, nullable=False, server_default=sa.text("''")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_feedback_job_id", "feedback", ["job_id"])
    op.create_index("ix_feedback_type", "feedback", ["feedback_type"])

    op.create_table(
        "metal_rates",
        sa.Column(
            "id", sa.Integer, primary_key=True, autoincrement=True
        ),
        sa.Column("metal", sa.String(32), nullable=False),
        sa.Column("rate_per_kg_inr", sa.Float, nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("rate_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ux_metal_rates_metal_date",
        "metal_rates",
        ["metal", "rate_date"],
        unique=True,
    )

    op.create_table(
        "fx_rates",
        sa.Column(
            "id", sa.Integer, primary_key=True, autoincrement=True
        ),
        sa.Column("pair", sa.String(16), nullable=False),
        sa.Column("rate", sa.Float, nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("rate_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ux_fx_rates_pair_date", "fx_rates", ["pair", "rate_date"], unique=True
    )

    op.create_table(
        "templates",
        sa.Column("template_id", sa.String(128), primary_key=True),
        sa.Column("product_family", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column(
            "description", sa.Text, nullable=False, server_default=sa.text("''")
        ),
        sa.Column("param_schema", postgresql.JSONB, nullable=False),
        sa.Column("regions", postgresql.JSONB, nullable=False),
        sa.Column(
            "active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_templates_product_family", "templates", ["product_family"]
    )


def downgrade() -> None:
    # Drop in reverse dependency order. FK-holding tables first.
    op.drop_index("ix_templates_product_family", table_name="templates")
    op.drop_table("templates")

    op.drop_index("ux_fx_rates_pair_date", table_name="fx_rates")
    op.drop_table("fx_rates")

    op.drop_index("ux_metal_rates_metal_date", table_name="metal_rates")
    op.drop_table("metal_rates")

    op.drop_index("ix_feedback_type", table_name="feedback")
    op.drop_index("ix_feedback_job_id", table_name="feedback")
    op.drop_table("feedback")

    op.drop_index("ix_cost_sheets_spec_id", table_name="cost_sheets")
    op.drop_table("cost_sheets")

    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_owner_id", table_name="jobs")
    op.drop_table("jobs")

    op.drop_index("ix_design_specs_template_id", table_name="design_specs")
    op.drop_index("ix_design_specs_brief_id", table_name="design_specs")
    op.drop_table("design_specs")

    op.drop_index("ix_briefs_owner_id", table_name="briefs")
    op.drop_table("briefs")

    # Leave pgvector installed on downgrade — other schemas may use it,
    # and removing extensions requires elevated privileges in production.
