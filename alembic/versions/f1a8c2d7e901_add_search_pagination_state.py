"""add search pagination state

Revision ID: f1a8c2d7e901
Revises: e032f5914315
Create Date: 2026-08-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f1a8c2d7e901"
down_revision: Union[str, Sequence[str], None] = "e032f5914315"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Store per-provider cursors alongside each cached search query."""

    op.add_column(
        "search_queries",
        sa.Column(
            "pagination_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove cached pagination state."""

    op.drop_column("search_queries", "pagination_state")
