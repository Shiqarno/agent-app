"""add user avatar id

Revision ID: e65eedab5e97
Revises: f20f1bba0219
Create Date: 2026-09-04 08:33:19.946937

Issue #20: adds `users.avatar_id`, a stable identifier into a fixed catalog
of 10 predefined avatars (no `Avatar` table -- the frontend owns mapping
each id to its bundled image asset). New Users get a random one assigned by
the ORM column default at insert time; this migration performs the
equivalent one-time backfill for every existing row, then makes the column
NOT NULL.

Random per-row (not a single shared server_default) so pre-existing Users
end up distributed across the same 10-avatar catalog new ones do, rather
than all landing on one avatar.
"""

import random
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e65eedab5e97"
down_revision: str | None = "f20f1bba0219"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matches app.models.AvatarId. Duplicated here (not imported) deliberately --
# this migration is a historical snapshot and must keep working even if the
# live model's catalog changes later.
_AVATAR_IDS = [f"avatar_{n:02d}" for n in range(1, 11)]


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_id", sa.String(length=16), nullable=True))

    connection = op.get_bind()
    users_table = sa.table("users", sa.column("id", sa.UUID()), sa.column("avatar_id", sa.String()))
    user_ids = connection.execute(sa.select(users_table.c.id)).scalars().all()
    for user_id in user_ids:
        connection.execute(
            users_table.update()
            .where(users_table.c.id == user_id)
            .values(avatar_id=random.choice(_AVATAR_IDS))
        )

    op.alter_column("users", "avatar_id", nullable=False)


def downgrade() -> None:
    op.drop_column("users", "avatar_id")
