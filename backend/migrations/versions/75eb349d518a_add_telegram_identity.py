"""add telegram identity

Revision ID: 75eb349d518a
Revises: d7cfadb5cf34
Create Date: 2026-09-07 12:00:00.000000

Issue #23: introduces `telegram_identities`, connecting one User to one
Telegram account. Both `user_id` and `telegram_user_id` are unique -- a User
has at most one Telegram account, and a Telegram account belongs to at most
one User -- enforced at the database level as the final integrity boundary
(see app.telegram_identity.activate_telegram_identity). No existing table
or column is modified.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "75eb349d518a"
down_revision: str | None = "d7cfadb5cf34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_telegram_identities_user_id"),
        sa.UniqueConstraint("telegram_user_id", name="uq_telegram_identities_telegram_user_id"),
    )


def downgrade() -> None:
    op.drop_table("telegram_identities")
