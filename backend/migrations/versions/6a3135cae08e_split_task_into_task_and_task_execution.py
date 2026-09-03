"""split task into task and task execution

Revision ID: 6a3135cae08e
Revises: 0bc60f330256
Create Date: 2026-09-03 18:47:09.220666

Breaking domain migration (Issue #18): splits the old Task (which mixed a
task *definition* with a single *execution* -- one assignee, one lifecycle
status) into:

  * Task       -- the reusable definition (title/description/reward_points/
                  is_active/created_by), no assignee, no lifecycle status.
  * TaskExecution -- one User's execution of a Task, owning the lifecycle
                  status that used to live on Task, plus an immutable
                  reward_points snapshot.

For every existing Task (every one had a mandatory `assigned_to` and
`status` under the old model), this creates exactly one corresponding
TaskExecution carrying over assigned_to -> user_id, status, reward_points,
and both timestamps -- so an already-COMPLETED task's history, and its
existing TASK_COMPLETED PointTransaction, both survive intact. The ledger
row is repointed from the old `task_id` to the new execution's id via
`task_execution_id`.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6a3135cae08e"
down_revision: str | None = "0bc60f330256"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_executions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reward_points", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "user_id", name="uq_task_executions_task_id_user_id"),
    )

    op.add_column(
        "tasks", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    # server_default only exists to satisfy the NOT NULL backfill for
    # existing rows; the application sets is_active explicitly on every new
    # Task, matching how every other column in this project is defaulted.
    op.alter_column("tasks", "is_active", server_default=None)

    op.add_column("point_transactions", sa.Column("task_execution_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "point_transactions_task_execution_id_fkey",
        "point_transactions",
        "task_executions",
        ["task_execution_id"],
        ["id"],
    )

    # --- Data migration: one TaskExecution per existing (assigned) Task ---
    connection = op.get_bind()
    tasks_table = sa.table(
        "tasks",
        sa.column("id", sa.UUID()),
        sa.column("status", sa.String()),
        sa.column("reward_points", sa.Integer()),
        sa.column("assigned_to", sa.UUID()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    task_executions_table = sa.table(
        "task_executions",
        sa.column("id", sa.UUID()),
        sa.column("task_id", sa.UUID()),
        sa.column("user_id", sa.UUID()),
        sa.column("status", sa.String()),
        sa.column("reward_points", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    point_transactions_table = sa.table(
        "point_transactions",
        sa.column("task_id", sa.UUID()),
        sa.column("task_execution_id", sa.UUID()),
    )

    existing_tasks = connection.execute(
        sa.select(
            tasks_table.c.id,
            tasks_table.c.status,
            tasks_table.c.reward_points,
            tasks_table.c.assigned_to,
            tasks_table.c.created_at,
            tasks_table.c.updated_at,
        )
    ).fetchall()

    for row in existing_tasks:
        if row.assigned_to is None:
            # Not reachable under the pre-#18 schema (assigned_to was
            # NOT NULL), handled defensively in case of unexpected data.
            continue
        execution_id = uuid.uuid4()
        connection.execute(
            task_executions_table.insert().values(
                id=execution_id,
                task_id=row.id,
                user_id=row.assigned_to,
                status=row.status,
                reward_points=row.reward_points,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
        connection.execute(
            point_transactions_table.update()
            .where(point_transactions_table.c.task_id == row.id)
            .values(task_execution_id=execution_id)
        )

    # --- Drop the now-migrated old columns/constraints ---
    op.drop_constraint("uq_point_transactions_task_id_reason", "point_transactions", type_="unique")
    op.drop_constraint("point_transactions_task_id_fkey", "point_transactions", type_="foreignkey")
    op.drop_column("point_transactions", "task_id")
    op.create_unique_constraint(
        "uq_point_transactions_task_execution_id_reason",
        "point_transactions",
        ["task_execution_id", "reason"],
    )

    op.drop_constraint("tasks_child_id_fkey", "tasks", type_="foreignkey")
    op.drop_column("tasks", "assigned_to")
    op.drop_column("tasks", "status")


def downgrade() -> None:
    op.add_column(
        "tasks", sa.Column("status", sa.String(length=32), autoincrement=False, nullable=True)
    )
    op.add_column("tasks", sa.Column("assigned_to", sa.UUID(), autoincrement=False, nullable=True))

    op.add_column(
        "point_transactions", sa.Column("task_id", sa.UUID(), autoincrement=False, nullable=True)
    )

    # --- Reverse data migration: fold each execution back onto its Task ---
    # MVP guarantees at most one execution per (task, user), but a Task
    # created post-#18 with direct assignment could still have only one
    # execution overall by construction of this app so far; a Task with
    # *multiple* executions (multiple Children having claimed it) has no
    # single (assigned_to, status) pair to fold back into -- downgrading
    # from a genuinely post-#18 multi-execution state is a deliberate data
    # loss (documented below), consistent with this being a one-way domain
    # migration in spirit; only the very first execution per Task is kept.
    connection = op.get_bind()
    tasks_table = sa.table(
        "tasks",
        sa.column("id", sa.UUID()),
        sa.column("status", sa.String()),
        sa.column("assigned_to", sa.UUID()),
    )
    task_executions_table = sa.table(
        "task_executions",
        sa.column("id", sa.UUID()),
        sa.column("task_id", sa.UUID()),
        sa.column("user_id", sa.UUID()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    point_transactions_table = sa.table(
        "point_transactions",
        sa.column("task_id", sa.UUID()),
        sa.column("task_execution_id", sa.UUID()),
    )

    executions = connection.execute(
        sa.select(
            task_executions_table.c.id,
            task_executions_table.c.task_id,
            task_executions_table.c.user_id,
            task_executions_table.c.status,
        ).order_by(task_executions_table.c.task_id, task_executions_table.c.created_at)
    ).fetchall()

    seen_task_ids: set[uuid.UUID] = set()
    for row in executions:
        if row.task_id in seen_task_ids:
            continue
        seen_task_ids.add(row.task_id)
        connection.execute(
            tasks_table.update()
            .where(tasks_table.c.id == row.task_id)
            .values(assigned_to=row.user_id, status=row.status)
        )
        connection.execute(
            point_transactions_table.update()
            .where(point_transactions_table.c.task_execution_id == row.id)
            .values(task_id=row.task_id)
        )

    # Any Task that never got an execution (created without assignment,
    # possible post-#18) can't downgrade to the old NOT NULL assigned_to
    # model meaningfully; leave assigned_to NULL for those rather than
    # inventing a fake assignee.

    op.create_foreign_key("tasks_child_id_fkey", "tasks", "users", ["assigned_to"], ["id"])
    op.drop_column("tasks", "is_active")

    op.drop_constraint(
        "uq_point_transactions_task_execution_id_reason", "point_transactions", type_="unique"
    )
    op.drop_constraint(
        "point_transactions_task_execution_id_fkey", "point_transactions", type_="foreignkey"
    )
    op.create_foreign_key(
        "point_transactions_task_id_fkey", "point_transactions", "tasks", ["task_id"], ["id"]
    )
    op.create_unique_constraint(
        "uq_point_transactions_task_id_reason", "point_transactions", ["task_id", "reason"]
    )
    op.drop_column("point_transactions", "task_execution_id")

    op.drop_table("task_executions")
