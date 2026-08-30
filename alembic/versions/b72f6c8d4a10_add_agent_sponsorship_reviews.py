"""add agent sponsorship reviews

Revision ID: b72f6c8d4a10
Revises: f1a8c2d7e901
Create Date: 2026-08-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b72f6c8d4a10"
down_revision: Union[str, Sequence[str], None] = "f1a8c2d7e901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create auditable storage for bounded Bedrock agent reviews."""

    op.create_table(
        "agent_sponsorship_reviews",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("agent_version", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("description_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("proposed_policy", sa.String(length=50), nullable=False),
        sa.Column("effective_policy", sa.String(length=50), nullable=False),
        sa.Column(
            "confidence",
            sa.Numeric(precision=5, scale=4),
            nullable=False,
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(precision=12, scale=8),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("reviewer_decision", sa.String(length=50), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["job_postings.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "agent_version",
            name="uq_job_agent_version",
        ),
    )
    op.create_index(
        op.f("ix_agent_sponsorship_reviews_job_id"),
        "agent_sponsorship_reviews",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_sponsorship_reviews_status"),
        "agent_sponsorship_reviews",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_sponsorship_reviews_proposed_policy"),
        "agent_sponsorship_reviews",
        ["proposed_policy"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_sponsorship_reviews_effective_policy"),
        "agent_sponsorship_reviews",
        ["effective_policy"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_sponsorship_reviews_requires_human_review"),
        "agent_sponsorship_reviews",
        ["requires_human_review"],
        unique=False,
    )


def downgrade() -> None:
    """Remove agent review storage."""

    op.drop_index(
        op.f("ix_agent_sponsorship_reviews_requires_human_review"),
        table_name="agent_sponsorship_reviews",
    )
    op.drop_index(
        op.f("ix_agent_sponsorship_reviews_effective_policy"),
        table_name="agent_sponsorship_reviews",
    )
    op.drop_index(
        op.f("ix_agent_sponsorship_reviews_proposed_policy"),
        table_name="agent_sponsorship_reviews",
    )
    op.drop_index(
        op.f("ix_agent_sponsorship_reviews_status"),
        table_name="agent_sponsorship_reviews",
    )
    op.drop_index(
        op.f("ix_agent_sponsorship_reviews_job_id"),
        table_name="agent_sponsorship_reviews",
    )
    op.drop_table("agent_sponsorship_reviews")
