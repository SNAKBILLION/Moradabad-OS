"""llm_calls table

Revision ID: c5d0a7f0b9d4
Revises: 48762f8fd95a
Create Date: 2026-04-24

Append-only log of every LLM call made by the intent layer. One row per
request attempt. Used for audit, debugging, and — once we have enough
examples — as a training-data source for fine-tuning.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d0a7f0b9d4"
down_revision: str | Sequence[str] | None = "48762f8fd95a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("call_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "brief_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("briefs.brief_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("succeeded", sa.Boolean, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("user_prompt", sa.Text, nullable=False),
        sa.Column("raw_response", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_llm_calls_brief_id", "llm_calls", ["brief_id"])
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"])
    op.create_index(
        "ix_llm_calls_prompt_hash", "llm_calls", ["prompt_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_llm_calls_prompt_hash", table_name="llm_calls")
    op.drop_index("ix_llm_calls_created_at", table_name="llm_calls")
    op.drop_index("ix_llm_calls_brief_id", table_name="llm_calls")
    op.drop_table("llm_calls")
