"""create users and tasks tables

Revision ID: 156295e1adad
Revises: f9cabd0370e6
Create Date: 2026-09-02 13:35:26.074514

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "156295e1adad"
down_revision: str | None = "f9cabd0370e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("adult", "child", name="userrole", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reward_points", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ASSIGNED",
                "IN_PROGRESS",
                "AWAITING_CONFIRMATION",
                "COMPLETED",
                name="taskstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("child_id", sa.UUID(), nullable=False),
        sa.Column("adult_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["adult_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["child_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("users")
