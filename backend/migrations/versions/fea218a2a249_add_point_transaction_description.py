"""add point transaction description

Revision ID: fea218a2a249
Revises: 75eb349d518a
Create Date: 2026-09-08 00:00:00.000000

Issue #31: adds `point_transactions.description`, a nullable free-text
field used only by manually-created (Adult) MANUAL_ADJUSTMENT rows to carry
the required human-readable reason. Existing TASK_COMPLETED/REWARD_REDEEMED
rows derive their description from a Task/Reward join instead and are left
NULL here -- no backfill, no other schema changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fea218a2a249"
down_revision: str | None = "75eb349d518a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("point_transactions", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("point_transactions", "description")
