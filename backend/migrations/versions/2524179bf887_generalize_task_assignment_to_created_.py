"""generalize task assignment to created_by and assigned_to

Revision ID: 2524179bf887
Revises: 156295e1adad
Create Date: 2026-09-02 14:23:04.819838

Renames tasks.adult_id -> tasks.created_by and tasks.child_id ->
tasks.assigned_to in place. This is a plain column rename (not a
drop/add), so existing rows and their values are preserved exactly:
every task's old adult_id becomes its created_by, and its old child_id
becomes its assigned_to. The foreign keys to users.id are unaffected by
the rename and keep working under their existing constraint names.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2524179bf887"
down_revision: str | None = "156295e1adad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("tasks", "adult_id", new_column_name="created_by")
    op.alter_column("tasks", "child_id", new_column_name="assigned_to")


def downgrade() -> None:
    op.alter_column("tasks", "assigned_to", new_column_name="child_id")
    op.alter_column("tasks", "created_by", new_column_name="adult_id")
