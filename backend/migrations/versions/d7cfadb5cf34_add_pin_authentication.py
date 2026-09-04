"""add pin authentication

Revision ID: d7cfadb5cf34
Revises: e65eedab5e97
Create Date: 2026-09-04 10:12:00.000000

Issue #22: introduces PIN login alongside the existing email/password login.

`user_credentials.password_hash` becomes nullable (a freshly-activated user
may choose to skip setting a password) and three new columns are added:
`pin_hash` (nullable -- existing users keep NULL until they complete
mandatory PIN setup; this migration deliberately does NOT generate or
derive a PIN for anyone), `pin_failed_attempts` (defaults to 0), and
`pin_locked_until` (nullable, set only while a temporary lockout is active).

No existing credential data is modified or destroyed -- every existing row's
`email`/`password_hash` is preserved exactly as-is.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7cfadb5cf34"
down_revision: str | None = "e65eedab5e97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("user_credentials", "password_hash", existing_type=sa.String(), nullable=True)
    op.add_column("user_credentials", sa.Column("pin_hash", sa.String(), nullable=True))
    op.add_column(
        "user_credentials",
        sa.Column("pin_failed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    # The server_default above only exists to satisfy the NOT NULL backfill
    # for existing rows; the application always sets this explicitly on
    # insert, matching this project's standing convention of not relying on
    # a permanent DB-level default elsewhere.
    op.alter_column("user_credentials", "pin_failed_attempts", server_default=None)
    op.add_column(
        "user_credentials",
        sa.Column("pin_locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_credentials", "pin_locked_until")
    op.drop_column("user_credentials", "pin_failed_attempts")
    op.drop_column("user_credentials", "pin_hash")
    # This fails loudly (a real NOT NULL violation) if any row has acquired
    # a NULL password_hash since upgrading -- e.g. a PIN-only activation
    # under the new model. That's the correct behavior: there is no sane
    # password to fabricate for such a row, so downgrading past this point
    # is a genuine, deliberate one-way door for any password-less user
    # created after the upgrade (matching this project's established
    # precedent of failing rather than inventing data on downgrade).
    op.alter_column("user_credentials", "password_hash", existing_type=sa.String(), nullable=False)
