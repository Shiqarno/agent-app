"""baseline: no schema objects yet

Revision ID: 28f4347134f4
Revises:
Create Date: 2026-09-01 13:03:54.488110

This is the first migration. It is intentionally empty: the application
does not yet define any tables (see app/models.py), so there is nothing
for Alembic to create. Its only purpose is to establish a migration
baseline (and the alembic_version bookkeeping row) so that future,
genuinely schema-changing migrations have a revision to build on.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "28f4347134f4"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
