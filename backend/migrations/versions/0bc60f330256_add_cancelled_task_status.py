"""add cancelled task status

Revision ID: 0bc60f330256
Revises: a3b3c7bb9311
Create Date: 2026-09-03 15:19:47.532724

Adds TaskStatus.CANCELLED (Issue #17). `tasks.status` is stored as a plain
VARCHAR(32) (SAEnum(..., native_enum=False)) with no database-level CHECK
constraint enforcing the set of valid values -- that validation happens at
the application layer (the Python StrEnum and Pydantic schemas). "CANCELLED"
also fits within the existing length(32) column, so no DDL change is
actually required; this migration exists only to keep the model-change ->
migration correspondence explicit and reviewable, matching the project's
convention of a migration per model change.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0bc60f330256"
down_revision: str | None = "a3b3c7bb9311"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
