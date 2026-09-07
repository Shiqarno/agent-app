# Telegram Bot UI

This is the authoritative source for user-visible Telegram behavior — what a
Child or Adult sees and can do in the bot. It describes accepted product
decisions, not implementation (no file names, callback formats, or code
structure — see `app/telegram/` and its own docstrings for that).

Business rules, authorization, and concurrency guarantees live in the
Application layer (`app/task_operations.py`, `app/reward_operations.py`,
`app/points_operations.py`); Telegram is presentation only.

## Identity and connection

A Telegram account is connected to exactly one `User` via an activation
token (`/start <token>`), the same mechanism as Web activation. An
unconnected account gets a short "ask the adult who manages your account"
message from every screen. Reconnecting a Telegram account to a different
User replaces the link; a Telegram account already linked to a different
User is refused, never silently reassigned.

`/start` with no token opens **Home**, whose content depends on the
connected User's role.

## Child navigation

```
Home (implicit — no separate Child Dashboard)
Tasks
My Tasks
Rewards
Points
```

### Tasks

The list of active Task definitions the Child can currently self-claim —
name and reward points only, no description, no history. Each has a
`Take` action.

### Take

Claims the Task and starts it in one step — there is no separate Start.
A successful Take creates a `TaskExecution` directly in `IN_PROGRESS`,
removes the Task from Tasks, and makes it visible in My Tasks.

### My Tasks

The Child's own non-terminal executions (`ASSIGNED`, `IN_PROGRESS`,
`AWAITING_CONFIRMATION`), newest first. An `IN_PROGRESS` item has `Done`;
an `AWAITING_CONFIRMATION` item shows "waiting for confirmation" and no
action. Completed/cancelled executions never appear here or suppress a
Task's future availability.

### Done

Transitions `IN_PROGRESS → AWAITING_CONFIRMATION`. No confirmation dialog,
no reason/comment, no points awarded yet — that happens only when an Adult
confirms.

### Rewards

The global reward catalog (not scoped by who created it), each showing
name, cost, and current balance context: `Get` when affordable, "Not
enough points" when not. `Get` redeems immediately at the reward's
*current* cost — never a cost cached from when the screen was rendered.

### Points

Current balance plus transaction history, newest first, paginated
("Older" loads more). Each entry shows a human-readable source (the Task
title for a completion, the Reward name for a redemption) and a signed
amount — never the internal ledger reason code.

## Adult navigation

```
Home
Tasks
Users        — not yet implemented in Telegram
Rewards      — Adult catalog management not yet implemented in Telegram
Points       — Adult view not yet implemented in Telegram
```

### Home

When executions are waiting for confirmation, Home leads with that queue
(name, Child, reward, count) and a way to view all. Otherwise it shows a
generic connected message pointing at the available commands (`/tasks`,
`/confirmations`, ...). Home is an action surface, not a dashboard — it
does not attempt to summarize everything at once.

### Confirmation

A queue of `TaskExecution`s currently `AWAITING_CONFIRMATION` — not a
separate domain entity, just that status. Any connected Adult may act on
any awaiting execution; there is no Adult↔Child ownership. Each item shows
the Task, the Child, and the reward snapshot, with `Confirm` (→
`COMPLETED`, exactly one `TASK_COMPLETED` point transaction) and `Return
to work` (→ back to `IN_PROGRESS`, no points). Both act immediately, no
confirmation dialog. There is no separate Confirmation Details screen.

### Tasks (Adult)

Manages the reusable Task-definition catalog — distinct from Child Tasks,
which is about claiming, not defining. Any Adult may manage any Task;
there is no per-Adult ownership in Telegram.

Each Task in the list shows its name, current reward, and availability:

- an active Task with no current open execution is **Available**;
- an active Task *with* one, or an inactive Task, is **Not available** —
  when there's a current open execution, its Child and state are shown
  (e.g. "Alex — in progress");
- terminal (completed/cancelled) executions never affect availability and
  are never shown here — this is not a history view.

Opening a Task shows its details: reward, availability, and (when one
exists) the current execution summary. From here an Adult can:

- **Edit** title and/or reward points — only when there is no current open
  execution;
- **Activate** an inactive Task, or **Deactivate** an active one — again,
  only with no current open execution;
- there is no direct assignment of a Task to a Child from Telegram, and no
  execution action (confirm/return) here — that stays in the separate
  Confirmation workflow.

Editing a Task's reward only changes future claims; every existing
`TaskExecution`'s reward snapshot is immutable.

**Add task** collects a name and a reward-points amount, in that order,
validated the same way as everywhere else in the app (non-blank title,
positive integer reward) — invalid input is rejected with a plain message
and the Adult can simply try again.

If a Task's state changes between when a screen was shown and when an
action is pressed (someone else edited it, or a Child claimed it in the
meantime), the action is re-validated against current state and refused
cleanly if it's no longer valid — the displayed screen is never trusted as
the source of truth.

## Out of scope (tracked, not yet built)

- Adult Rewards/Points views, and manual point adjustments.
- Direct assignment of a Task to a specific Child from Telegram.
- Task/description editing beyond title and reward points.
- Task, execution, or redemption history views.
- Notifications, reminders, comments/reasons, attachments.
- Any Adult↔Child ownership or family-grouping concept — deliberately not
  part of this product's model.
