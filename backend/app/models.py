import random
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserRole(StrEnum):
    ADULT = "adult"
    CHILD = "child"


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


class AvatarId(StrEnum):
    """The fixed catalog of 10 selectable avatars (Issue #20). A stable
    identifier, not a filesystem path or URL -- the frontend owns mapping
    each id to its bundled image asset.
    """

    AVATAR_01 = "avatar_01"
    AVATAR_02 = "avatar_02"
    AVATAR_03 = "avatar_03"
    AVATAR_04 = "avatar_04"
    AVATAR_05 = "avatar_05"
    AVATAR_06 = "avatar_06"
    AVATAR_07 = "avatar_07"
    AVATAR_08 = "avatar_08"
    AVATAR_09 = "avatar_09"
    AVATAR_10 = "avatar_10"


def _random_avatar_id() -> AvatarId:
    return random.choice(list(AvatarId))


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False,
    )
    # Assigned at insert time by this column default -- not by router code --
    # so every path that creates a User (POST /api/users, /api/auth/setup,
    # test helpers that construct User(...) directly) gets a random initial
    # avatar automatically, with no way for request input to override it
    # (Issue #20: the client never supplies avatar_id at creation).
    avatar_id: Mapped[AvatarId] = mapped_column(
        SAEnum(AvatarId, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False,
        default=_random_avatar_id,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaskExecutionStatus(StrEnum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Task(Base):
    """A reusable task *definition* (Issue #18). Carries no executor and no
    lifecycle status of its own -- those belong to TaskExecution, of which a
    Task may have any number (including zero).

    `is_active` (Issue #19) is a single self-claim *slot*, not a general
    "is this task usable" flag: `True` means exactly one Child may currently
    self-claim this Task; a successful claim atomically flips it back to
    `False`, so at most one self-claim can ever be in flight for a Task at a
    time. It is otherwise independent of any TaskExecution's own lifecycle
    -- reactivating a Task never touches existing executions, and an Adult
    may reactivate it while an earlier execution is still in progress, which
    is exactly how the same Task becomes claimable by another Child (or the
    same Child again, once their prior execution has gone terminal) without
    ever mutating that earlier execution.
    """

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    reward_points: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaskExecution(Base):
    """A specific User's execution of a Task (Issue #18). Owns the lifecycle
    that used to live directly on Task, plus an immutable reward_points
    snapshot taken from the Task at creation time -- later changes to
    Task.reward_points never affect an existing execution.

    Invariant (Issue #19): at most one *non-terminal* execution may exist
    per (task_id, user_id) at a time, enforced by the partial unique index
    below rather than a plain UniqueConstraint. A User may accumulate any
    number of COMPLETED/CANCELLED (terminal) executions of the same Task
    over time -- each self-claim, or reassignment, of a Task they've
    already finished (or been taken off of) starts a brand new execution
    row rather than reopening the old one -- but can never hold two
    open (ASSIGNED/IN_PROGRESS/AWAITING_CONFIRMATION) executions of the
    same Task simultaneously.
    """

    __tablename__ = "task_executions"
    __table_args__ = (
        Index(
            "uq_task_executions_task_id_user_id_open",
            "task_id",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('ASSIGNED', 'IN_PROGRESS', 'AWAITING_CONFIRMATION')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[TaskExecutionStatus] = mapped_column(
        SAEnum(TaskExecutionStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=TaskExecutionStatus.ASSIGNED,
    )
    reward_points: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PointTransactionReason(StrEnum):
    TASK_COMPLETED = "TASK_COMPLETED"
    REWARD_REDEEMED = "REWARD_REDEEMED"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    GOAL_CONTRIBUTION = "GOAL_CONTRIBUTION"


class PointTransaction(Base):
    __tablename__ = "point_transactions"
    __table_args__ = (
        UniqueConstraint(
            "task_execution_id", "reason", name="uq_point_transactions_task_execution_id_reason"
        ),
        # Same concurrency backstop as the constraint above, for the
        # symmetric case (Issue #39): confirming a Reward request holds a
        # row lock on the RewardRedemption for its status check, exactly
        # like confirming a TaskExecution does, but this constraint is the
        # database-level defense-in-depth against a duplicate
        # REWARD_REDEEMED row for the same redemption, the way the
        # task_execution_id constraint already is for TASK_COMPLETED.
        # NULL task_execution_id/redemption_id rows never collide with each
        # other under either constraint (Postgres treats each NULL as
        # distinct), so this coexists safely with all existing rows.
        UniqueConstraint(
            "redemption_id", "reason", name="uq_point_transactions_redemption_id_reason"
        ),
        # Same rationale again for GoalContribution (Issue: Goals): a
        # database-level guarantee that a given contribution can never end
        # up with two GOAL_CONTRIBUTION rows, even though (unlike the two
        # constraints above) contribute_to_goal creates both rows in one
        # single-step transaction rather than a later, separate confirm
        # step -- defense-in-depth against a future duplicate-processing
        # bug, not a currently-reachable race.
        UniqueConstraint(
            "goal_contribution_id",
            "reason",
            name="uq_point_transactions_goal_contribution_id_reason",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    task_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_executions.id"), nullable=True
    )
    redemption_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reward_redemptions.id"), nullable=True
    )
    goal_contribution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goal_contributions.id"), nullable=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[PointTransactionReason] = mapped_column(
        SAEnum(PointTransactionReason, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
    )
    # Only populated for MANUAL_ADJUSTMENT rows (Issue #31) -- a
    # TASK_COMPLETED/REWARD_REDEEMED/GOAL_CONTRIBUTION row's human-readable
    # description is derived from its Task/Reward/Goal join instead, so
    # this stays NULL there.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Reward(Base):
    __tablename__ = "rewards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cost_points: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RewardRedemptionStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class RewardRedemption(Base):
    """A Child's request for a Reward (Issue #39). `status` distinguishes a
    still-pending request from a terminal one:

    - `PENDING_CONFIRMATION` -- requested, `cost_points` frozen against the
      requester's available balance, no ledger entry yet.
    - `CONFIRMED` -- an Adult approved it; exactly one `REWARD_REDEEMED`
      `PointTransaction` exists for this redemption's `id`, and the freeze
      is released (it no longer counts toward "active frozen" -- the cost
      is now a real ledger deduction instead).
    - `REJECTED` -- an Adult declined it; the freeze is released and no
      `PointTransaction` is ever created for it.

    The direct-redemption path (`reward_operations.redeem_reward`, used by
    the Web `/redeem` endpoint and left otherwise unchanged by Issue #39)
    creates a redemption already `CONFIRMED`, atomically with its
    `PointTransaction` -- there is no pending phase for that path, matching
    its pre-existing, unchanged contract. Only the Telegram request flow
    (`request_reward_redemption` / `confirm_reward_redemption` /
    `reject_reward_redemption`) ever creates or transitions a
    `PENDING_CONFIRMATION` row.
    """

    __tablename__ = "reward_redemptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rewards.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    cost_points: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RewardRedemptionStatus] = mapped_column(
        SAEnum(RewardRedemptionStatus, native_enum=False, length=32, values_callable=_enum_values),
        nullable=False,
        default=RewardRedemptionStatus.CONFIRMED,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class Goal(Base):
    """A global savings target a Child accumulates points toward (Issue:
    Goals) -- not a Reward: a Reward is *spent* out of a Child's balance in
    one step, a Goal is *accumulated* into over any number of transfers,
    by any number of Children, via GoalContribution below. `accumulated_points`
    is a denormalized running total for cheap reads (Goal details, the
    Child `/goals` list); GoalContribution rows remain the source of truth
    for how it got there, exactly like PointTransaction is for a User's own
    balance -- `goal_operations.contribute_to_goal` is the only place that
    ever advances it, always in the same transaction as the
    GoalContribution/PointTransaction pair that justifies the change.

    `status` starts `ACTIVE` and becomes `COMPLETED` once
    `accumulated_points >= cost_points` -- never re-opened afterward (no
    `ACTIVE`-`COMPLETED` back-transition exists in this Issue). A
    `COMPLETED` Goal is refused for further edits or contributions but is
    never deleted -- it remains visible, with its full history intact.
    """

    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    cost_points: Mapped[int] = mapped_column(Integer, nullable=False)
    accumulated_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[GoalStatus] = mapped_column(
        SAEnum(GoalStatus, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False,
        default=GoalStatus.ACTIVE,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoalContribution(Base):
    """One Child's single point transfer into a Goal (Issue: Goals) --
    immutable once created, exactly like PointTransaction: never updated or
    deleted by normal application operations, and it is the source of a
    Goal's transfer history. Deliberately its own table, not a reuse of
    RewardRedemption -- a Goal accumulates from any number of these over
    time, across any number of different Children, unlike a
    RewardRedemption's one-Child, one-shot request/resolve shape.
    """

    __tablename__ = "goal_contributions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserCredential(Base):
    """(Issue #22) `password_hash` and `pin_hash` are each independently
    optional: a freshly-activated user always has a PIN but may have no
    password, while a user who predates PIN login has a password but
    `pin_hash IS NULL` until they complete mandatory PIN setup. At least one
    of the two is always non-null in practice (activation requires a PIN,
    and the original password-only setup/activation paths are gone), but
    that isn't enforced at the DB level -- both columns are simply nullable.
    """

    __tablename__ = "user_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    pin_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    pin_failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pin_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserActivation(Base):
    __tablename__ = "user_activations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class TelegramIdentity(Base):
    """Connects one User to one Telegram account (Issue #23). Deliberately
    not a generic "Identity" abstraction -- this is Telegram-specific, and
    Web identity continues to be resolved through UserSession exactly as
    before. Both `user_id` and `telegram_user_id` are unique: a User has at
    most one Telegram account, and a Telegram account belongs to at most
    one User. No `role` column -- role stays on `User`.
    """

    __tablename__ = "telegram_identities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False
    )
    # Telegram user ids are 64-bit and can exceed Postgres's 32-bit Integer
    # range, so this must be BigInteger, not Integer.
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
