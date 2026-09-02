"""create point transactions table

Revision ID: ca4f050fbc5a
Revises: 2524179bf887
Create Date: 2026-09-02 14:49:11.264654

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ca4f050fbc5a"
down_revision: str | None = "2524179bf887"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "point_transactions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "TASK_COMPLETED",
                name="pointtransactionreason",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "reason", name="uq_point_transactions_task_id_reason"),
    )


def downgrade() -> None:
    op.drop_table("point_transactions")
