"""add reward redemptions and negative point transactions

Revision ID: 9e7726fe94c9
Revises: cf123d4b59e3
Create Date: 2026-09-02 16:42:33.654386

Adds the reward_redemptions table and links it to point_transactions via a
new nullable redemption_id column, so a REWARD_REDEEMED transaction can be
traced back to the redemption that created it (mirroring the existing
task_id link for TASK_COMPLETED transactions).

point_transactions.task_id becomes nullable: REWARD_REDEEMED transactions
have no associated Task, only TASK_COMPLETED transactions do. The existing
uq_point_transactions_task_id_reason constraint continues to work correctly
for TASK_COMPLETED rows once task_id is nullable, since Postgres treats each
NULL as distinct for uniqueness purposes (so any number of NULL-task_id
REWARD_REDEEMED rows can coexist without violating it).

Note: downgrade() restores task_id to NOT NULL, which will fail if any
REWARD_REDEEMED transactions (task_id = NULL) already exist -- this is an
inherent, expected limitation of reversing a constraint relaxation once data
that depends on the relaxation has been created, not something this
migration can resolve without deleting that data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e7726fe94c9"
down_revision: str | None = "cf123d4b59e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reward_redemptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("reward_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("cost_points", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["reward_id"], ["rewards.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("point_transactions", sa.Column("redemption_id", sa.UUID(), nullable=True))
    op.alter_column("point_transactions", "task_id", existing_type=sa.UUID(), nullable=True)
    op.create_foreign_key(
        "point_transactions_redemption_id_fkey",
        "point_transactions",
        "reward_redemptions",
        ["redemption_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "point_transactions_redemption_id_fkey", "point_transactions", type_="foreignkey"
    )
    op.alter_column("point_transactions", "task_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("point_transactions", "redemption_id")
    op.drop_table("reward_redemptions")
