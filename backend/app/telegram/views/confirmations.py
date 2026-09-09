from dataclasses import dataclass
from datetime import datetime

from app.models import Reward, RewardRedemption, Task, TaskExecution, User

CONFIRMATIONS_HEADING = "Подтверждения"
NO_CONFIRMATIONS_TEXT = "Nothing waiting for confirmation."


@dataclass(frozen=True)
class TaskConfirmationItem:
    """A Task execution awaiting confirmation, wrapped for the combined
    Adult /confirmations queue (Issue #39), which now also carries pending
    Reward requests. Never constructed by the Application layer -- this is
    a Telegram-adapter presentation concern, not a domain concept.
    """

    execution: TaskExecution
    task: Task
    child: User

    @property
    def created_at(self) -> datetime:
        return self.execution.created_at


@dataclass(frozen=True)
class RewardConfirmationItem:
    """A Reward request awaiting confirmation (Issue #39) -- the Reward
    counterpart of TaskConfirmationItem above, sharing the same queue.
    """

    redemption: RewardRedemption
    reward: Reward
    child: User

    @property
    def created_at(self) -> datetime:
        return self.redemption.created_at


ConfirmationItem = TaskConfirmationItem | RewardConfirmationItem


def render_confirmation_list(items: list[ConfirmationItem]) -> str:
    """Issue #36 step 1 / Issue #39: just the heading -- each item's name
    lives only on its own button (confirmation_list_keyboard), never
    duplicated as a separate text block above it. Task executions and
    Reward requests share this one list.
    """
    if not items:
        return f"{CONFIRMATIONS_HEADING}\n\n{NO_CONFIRMATIONS_TEXT}"
    return CONFIRMATIONS_HEADING


def render_confirmation_detail(execution: TaskExecution, task: Task, child: User) -> str:
    """Issue #36 step 2: the selected execution's own Task name, Child, and
    reward snapshot -- shown once here, not on the Confirm/Return buttons
    beneath it (confirmation_detail_keyboard).
    """
    return f"{task.title}\n\n{child.name} · 💰 {execution.reward_points}"


def render_execution_confirmed(task: Task, child: User, execution: TaskExecution) -> str:
    return f"{task.title} confirmed -- {child.name} earned 💰 {execution.reward_points}."


def render_execution_returned(task: Task, child: User) -> str:
    return f"{task.title} returned to {child.name}."


def render_reward_confirmation_detail(
    redemption: RewardRedemption, reward: Reward, child: User
) -> str:
    """The Reward request analogue of render_confirmation_detail above
    (Issue #39) -- the selected request's Reward name, Child, and frozen
    cost snapshot.
    """
    return f"{reward.name}\n{child.name}\n\n{redemption.cost_points} points"


def render_reward_redemption_confirmed(
    redemption: RewardRedemption, reward: Reward, child: User
) -> str:
    return f"{reward.name} confirmed -- {child.name} redeemed {redemption.cost_points} points."


def render_reward_redemption_rejected(reward: Reward, child: User) -> str:
    return f"{reward.name} request declined for {child.name}."
