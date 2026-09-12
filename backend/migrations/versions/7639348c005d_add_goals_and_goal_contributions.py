"""add goals and goal contributions

Revision ID: 7639348c005d
Revises: 8db33484bb04
Create Date: 2026-09-12 15:16:10.000000

Issue: Goals. Adds `goals` (a global savings target, `status` ACTIVE ->
COMPLETED, with a denormalized `accumulated_points` running total) and
`goal_contributions` (one immutable row per Child transfer into a Goal --
deliberately its own table, never a reuse of `reward_redemptions`).

Also adds a nullable `goal_contribution_id` to `point_transactions` (mirrors
the existing `task_execution_id`/`redemption_id` columns) so a
GOAL_CONTRIBUTION transaction can be traced back to the contribution that
created it, plus the matching `uq_point_transactions_goal_contribution_id_reason`
unique constraint -- the same database-level defense-in-depth the two
existing FK+reason constraints already provide.

`PointTransactionReason` gains `GOAL_CONTRIBUTION` in the Python-side enum
only: `reason` is `native_enum=False` (a plain VARCHAR, not a Postgres
ENUM type -- see the original create_point_transactions_table migration),
so no DDL is needed to allow the new value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7639348c005d"
down_revision: str | None = "8db33484bb04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("cost_points", sa.Integer(), nullable=False),
        sa.Column("accumulated_points", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "COMPLETED",
                name="goalstatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "goal_contributions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("goal_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column(
        "point_transactions", sa.Column("goal_contribution_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "point_transactions_goal_contribution_id_fkey",
        "point_transactions",
        "goal_contributions",
        ["goal_contribution_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_point_transactions_goal_contribution_id_reason",
        "point_transactions",
        ["goal_contribution_id", "reason"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_point_transactions_goal_contribution_id_reason",
        "point_transactions",
        type_="unique",
    )
    op.drop_constraint(
        "point_transactions_goal_contribution_id_fkey", "point_transactions", type_="foreignkey"
    )
    op.drop_column("point_transactions", "goal_contribution_id")
    op.drop_table("goal_contributions")
    op.drop_table("goals")
