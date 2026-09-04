"""single active claim slot for task

Revision ID: f20f1bba0219
Revises: 6a3135cae08e
Create Date: 2026-09-04 06:11:41.971904

Issue #19: a Task's `is_active` becomes a single self-claim *slot* rather
than a general enable/disable flag. A successful claim now atomically
creates the TaskExecution and closes the slot; only an explicit Adult
reactivation reopens it. This makes a Task legitimately reusable over time
-- the same Child may claim the same Task again after reactivation, once
their earlier execution has gone terminal, and different Children may each
hold their own execution of the same Task across different points in time
(or, since reactivation never touches other executions, even while an
earlier one is still open).

This retires `uq_task_executions_task_id_user_id`, the old full
UNIQUE(task_id, user_id) constraint, which enforced "a User may execute a
Task at most once, ever" -- exactly the old rule Issue #19 replaces. In its
place, a partial unique index enforces the actual invariant: a User may
never hold two simultaneously *non-terminal* (ASSIGNED / IN_PROGRESS /
AWAITING_CONFIRMATION) executions of the same Task. Terminal (COMPLETED /
CANCELLED) executions are excluded from the index entirely, so historical
executions accumulate freely.

No existing data can violate the new, strictly looser constraint (every row
that satisfied the old *unconditional* uniqueness trivially satisfies this
conditional one too), so this is a pure constraint swap -- no backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f20f1bba0219"
down_revision: str | None = "6a3135cae08e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN_STATUSES_SQL = "status IN ('ASSIGNED', 'IN_PROGRESS', 'AWAITING_CONFIRMATION')"


def upgrade() -> None:
    op.drop_constraint("uq_task_executions_task_id_user_id", "task_executions", type_="unique")
    op.create_index(
        "uq_task_executions_task_id_user_id_open",
        "task_executions",
        ["task_id", "user_id"],
        unique=True,
        postgresql_where=sa.text(_OPEN_STATUSES_SQL),
    )


def downgrade() -> None:
    # The old constraint is strictly stricter than the new one, so data
    # accumulated under Issue #19's model (e.g. the same (task_id, user_id)
    # pair appearing across several terminal executions) can violate it.
    # Rather than silently discarding history, keep only the most-recently-
    # created execution per (task_id, user_id) among rows that are safe to
    # drop -- one with no PointTransaction referencing it is never deleted,
    # matching this project's standing rule to never corrupt ledger history,
    # even on downgrade. If a genuine conflict remains (multiple executions
    # of the same (task, user) pair each with their own completed-and-paid
    # ledger entry -- precisely the scenario Issue #19 was built to allow),
    # recreating the strict constraint below fails loudly instead.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            DELETE FROM task_executions te
            USING (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY task_id, user_id
                           ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM task_executions
            ) ranked
            WHERE te.id = ranked.id
              AND ranked.rn > 1
              AND NOT EXISTS (
                  SELECT 1 FROM point_transactions pt
                  WHERE pt.task_execution_id = te.id
              )
            """
        )
    )

    op.drop_index("uq_task_executions_task_id_user_id_open", table_name="task_executions")
    op.create_unique_constraint(
        "uq_task_executions_task_id_user_id", "task_executions", ["task_id", "user_id"]
    )
