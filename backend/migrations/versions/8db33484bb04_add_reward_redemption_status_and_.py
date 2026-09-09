"""add reward redemption status and pending confirmation flow

Revision ID: 8db33484bb04
Revises: fea218a2a249
Create Date: 2026-09-09 06:48:37.652060

Issue #39: `RewardRedemption` gains `status` (PENDING_CONFIRMATION /
CONFIRMED / REJECTED), replacing the old "a RewardRedemption row always
means an already-completed redemption" assumption. Every existing row
predates this and was created by the old always-immediate `redeem_reward`
flow, so it backfills to CONFIRMED -- exactly what it already was in
effect, just now represented explicitly rather than implicitly.

Also adds `uq_point_transactions_redemption_id_reason`, the same
concurrency backstop `uq_point_transactions_task_execution_id_reason`
already provides for TASK_COMPLETED confirmations, now for REWARD_REDEEMED
ones (a Reward request's Confirm action holds a row lock on the
RewardRedemption for its status check, exactly like TaskExecution
confirmation does; this constraint is the database-level defense-in-depth
behind that lock). No existing row can violate it: every REWARD_REDEEMED
transaction created by the pre-Issue-#39 `redeem_reward` flow already has
its own freshly-generated, one-to-one redemption_id, and NULL
redemption_id (every TASK_COMPLETED/MANUAL_ADJUSTMENT row) never collides
with another NULL under a unique constraint.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8db33484bb04"
down_revision: str | None = "fea218a2a249"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_point_transactions_redemption_id_reason",
        "point_transactions",
        ["redemption_id", "reason"],
    )

    op.add_column(
        "reward_redemptions",
        sa.Column(
            "status",
            sa.Enum(
                "PENDING_CONFIRMATION",
                "CONFIRMED",
                "REJECTED",
                name="rewardredemptionstatus",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
    )
    op.execute("UPDATE reward_redemptions SET status = 'CONFIRMED'")
    op.alter_column("reward_redemptions", "status", nullable=False)


def downgrade() -> None:
    op.drop_column("reward_redemptions", "status")
    op.drop_constraint(
        "uq_point_transactions_redemption_id_reason", "point_transactions", type_="unique"
    )
