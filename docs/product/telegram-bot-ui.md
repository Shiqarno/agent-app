# Telegram Bot UI

This is the authoritative source for user-visible Telegram behavior — what a
Child or Adult sees and can do in the bot. It describes accepted product
decisions, not implementation (no file names, callback formats, or code
structure — see `app/telegram/` and its own docstrings for that).

Business rules, authorization, and concurrency guarantees live in the
Application layer (`app/task_operations.py`, `app/reward_operations.py`,
`app/points_operations.py`, `app/user_operations.py`); Telegram is
presentation only.

## Identity and connection

A Telegram account is connected to exactly one `User` via an activation
token (`/start <token>`), the same mechanism as Web activation. An
unconnected account gets a short "ask the adult who manages your account"
message from every screen. Reconnecting a Telegram account to a different
User replaces the link; a Telegram account already linked to a different
User is refused, never silently reassigned.

The Adult obtains the `/start` link for any not-yet-connected User —
Adult or Child — from the Web app (Users → a User → Telegram), which
shows whether that User is connected and, if not, a `Get activation link`
action producing a `t.me` deep link to send them — the same underlying
token/link the Web sign-up flow already uses, just presented for
Telegram. Having Web credentials or not has no bearing on Telegram
eligibility, and vice versa; nor does role.

`/start` with no token opens **Home**, whose content depends on the
connected User's role.

### Command panel

Telegram's own command menu (the "/" button) is role-aware: a connected
Child sees `/start`, `/tasks`, `/mytasks`, `/rewards`, `/points`; a
connected Adult sees `/start`, `/users`, `/tasks`, `/confirmations`,
`/rewards`, `/points` — never the other role's commands. An account not
yet connected to any User sees only `/start`. The menu is refreshed every
time `/start` is used, so it always matches the currently-connected
User's role.

## Child navigation

```
Home (implicit — no separate Child Dashboard)
Tasks
My Tasks
Rewards
Points
```

### Home

No separate Child Dashboard — `/start` shows the Child's current overall
Points balance ("Твои баллы: 💰 N", read fresh from the Point Ledger,
never a stored value) above the same navigation hints as before.

Every points amount shown anywhere in the bot — a balance, a reward, a
cost, a transaction — uses the same 💰 notation (💰 followed by the
number), never the literal word "pts". This is a single, consistent
visual convention across every screen in both the Child and Adult
navigation; it never changes the underlying numeric value or point
semantics, only how it's displayed.

### Tasks

Headed "Доступные задачи". The list of active Task definitions the Child
can currently self-claim — no description, no history. A Task's name
appears nowhere but its own button, alongside its reward (💰 notation) —
no verb on the button either, since tapping it is self-evidently the
action, so nothing is ever shown twice.

### Take

Claims the Task and starts it in one step — there is no separate Start.
A successful Take creates a `TaskExecution` directly in `IN_PROGRESS`,
removes the Task from Tasks, and makes it visible in My Tasks.

### My Tasks

Headed "Твои задачи". The Child's own non-terminal executions
(`ASSIGNED`, `IN_PROGRESS`, `AWAITING_CONFIRMATION`), newest first. An
`ASSIGNED` item is fully represented by its own button (name + reward, no
verb) that starts it; an `IN_PROGRESS` item's button (same shape) marks it
done — neither button says "Start" or "Done", since tapping either is
self-evidently the action, and neither Task's name appears anywhere but
its own button. An `AWAITING_CONFIRMATION` item has no button at all (no
action is possible on it), so it's shown as text instead — name, reward,
and "waiting for confirmation". Every reward shown (💰 notation) is
always the amount actually snapshotted onto *that* execution when it
began, never a Task's reward if it was edited since. Completed/cancelled
executions never appear here or suppress a Task's future availability.

### Start

Transitions `ASSIGNED → IN_PROGRESS` on the same `TaskExecution` the Adult
created — no new execution, no confirmation dialog.

### Done

Transitions `IN_PROGRESS → AWAITING_CONFIRMATION`. No confirmation dialog,
no reason/comment, no points awarded yet — that happens only when an Adult
confirms.

### Rewards

Headed "Доступные награды", followed by the Child's current balance. The
global reward catalog (not scoped by who created it): an affordable
Reward is fully represented by its own button (name + cost, 💰 notation,
no verb) — tapping it redeems immediately at the reward's *current* cost,
never a cost cached from when the screen was rendered. A Reward the Child
can't currently afford gets no button (nothing to tap), so it's shown as
text instead — name, cost, and "Not enough points" — the only case a
Reward's name appears anywhere but a button.

### Points

Current balance plus transaction history, newest first, paginated
("Older" loads more). Each entry shows a human-readable source (the Task
title for a completion, the Reward name for a redemption) and a signed
amount — never the internal ledger reason code.

## Adult navigation

```
Home
Tasks
Users
Rewards
Points
```

### Home

`/start` *is* the Confirmation queue — the exact same screen `/confirmations`
itself shows, not a separate preview or summary. Home is an action
surface, not a dashboard: it does not attempt to summarize everything at
once, and it never auto-confirms or auto-returns anything just because
the Adult opened it.

### Confirmation

A queue of `TaskExecution`s currently `AWAITING_CONFIRMATION` — not a
separate domain entity, just that status. Any connected Adult may act on
any awaiting execution; there is no Adult↔Child ownership. A two-step
flow:

1. **The list** — one button per awaiting execution, showing the Task's
   name and the Child's name (needed to tell apart two Children awaiting
   confirmation on the same Task); nothing is duplicated as separate text
   above it.
2. **The selected execution** — tapping a Task shows its name, the Child,
   and the reward snapshot (💰 notation), together with `Confirm` (→
   `COMPLETED`, exactly one `TASK_COMPLETED` point transaction) and
   `Return to work` (→ back to `IN_PROGRESS`, no points). A `← Back`
   action returns to the list without acting. Both `Confirm` and
   `Return to work` act immediately, no further confirmation dialog, and
   afterward return to the (now refreshed) list.

Selecting one execution never exposes or affects another's controls.

### Tasks (Adult)

Headed "Все задачи". Manages the reusable Task-definition catalog —
distinct from Child Tasks, which is about claiming, not defining. Any
Adult may manage any Task; there is no per-Adult ownership in Telegram.

Each Task is fully represented by its own button, and nothing is
duplicated as separate text alongside the list. Whether the Task is
currently open for **self-claim** — `is_active`, its own single
self-claim slot, never whether the Task has any executions at all —
decides the button's whole shape, not just a word on it:

- an active Task's button shows its name and current reward, plain:
  `Task name · 💰 reward`;
- an inactive Task's button shows a `❌` marker followed by its plain
  name, with no reward amount at all: `❌ Task name` — the reward is
  intentionally omitted, since the button represents an unavailable
  self-claim offer, not a reward-bearing action;
- this reflects `is_active` alone — a Task can be active with a current
  open execution (e.g. directly assigned) and still shows plain with its
  reward, since self-claim availability and execution state are
  independent.

A Task can have more than one open execution at once for different
Children (one self-claimed, others directly assigned, or several
self-claimed across a deactivate/reactivate cycle) — that detail, and
which Child currently has it and its state (e.g. "Alex — in progress"),
lives one tap further in, on Task Details; terminal (completed/cancelled)
executions never affect availability and are never shown there either —
this is not a history view.

Opening a Task shows its details: reward, availability, and (when one
exists) the current execution summary. From here an Adult can:

- **Edit** title and/or reward points — only when there is no current open
  execution, since an edit could otherwise change the terms of work
  already underway;
- **Activate** an inactive Task, or **Deactivate** an active one — always
  available, regardless of any current open execution: `is_active` is a
  self-claim slot, entirely independent of whatever executions the Task
  already has, so toggling it never touches them. An Adult can freely
  reopen a Task's self-claim slot while one or more Children already have
  an open execution of it (letting another Child claim it too), or close
  it without disturbing anyone already working on it;
- **Assign** the Task directly to a Child — always available, regardless
  of `is_active` or of any other open execution, since direct assignment
  is independent of both;
- there is no execution action (confirm/return) here — that stays in the
  separate Confirmation workflow.

Editing a Task's reward only changes future claims; every existing
`TaskExecution`'s reward snapshot is immutable. Assigning a Task never
changes `is_active`, never touches any other `TaskExecution`, and never
changes the Task's reward — it only creates one new `ASSIGNED` execution
for the chosen Child, with the Task's *current* reward snapshotted into it.
The same (Task, Child) pairing can never have two simultaneous open
executions — that per-Child uniqueness is the only limit on how many
Children may hold an open execution of the same Task at once.

### Assign

Shows every Child eligible to receive this Task — every Child except one
who already has an open (`ASSIGNED`/`IN_PROGRESS`/`AWAITING_CONFIRMATION`)
execution of it; a Child whose only executions of this Task are terminal
remains eligible. If no Child is eligible, the screen says so plainly
rather than showing an empty list. Selecting a Child assigns the Task to
them immediately — a new `ASSIGNED` `TaskExecution` — and confirms with
the Child's name; there is no separate confirmation dialog. Assignment is
one Child at a time; there is no bulk or recurring assignment.

**Add task** collects a name and a reward-points amount, in that order,
validated the same way as everywhere else in the app (non-blank title,
positive integer reward) — invalid input is rejected with a plain message
and the Adult can simply try again.

If a Task's state changes between when a screen was shown and when an
action is pressed (someone else edited it, or a Child claimed it in the
meantime), the action is re-validated against current state and refused
cleanly if it's no longer valid — the displayed screen is never trusted as
the source of truth.

### Users

An identity/onboarding surface — not a dashboard. It does not show task
history, points balance, reward history, or any Telegram-internal detail
like a numeric account id or an activation token. Any Adult may manage
any User; there is no per-Adult ownership in Telegram, and there is still
no permanent Adult↔Child relationship anywhere in the product.

Each User is fully represented by their own button (just their name) —
nothing is duplicated as separate text alongside the list; role and
connection status aren't shown at the list level at all.

Opening a User is where those facts live: name, role, and whether their
Telegram account is connected — a selected-entity screen, not the list,
so showing them here isn't duplication. For an unconnected Child, this is
also where an Adult gets **Get activation link** — never shown once that
Child is connected, and never usable to reconnect or replace an
already-connected account (that stays out of scope; the existing
activation/identity rules are unchanged).

**Add Child** collects just a name, validated the same way as everywhere
else (non-blank) — invalid input is rejected with a plain message and the
Adult can simply try again. Creating a Child immediately produces an
activation link to send them:

```
Alex was created.

Send this activation link to Alex:

https://t.me/<bot>?start=<token>

The link expires in 72 hours.
```

Generating a fresh link for an existing unconnected Child (because the
first one was lost or expired) shows the same kind of message, without the
"was created" line, and immediately invalidates whatever link existed
before it — only one activation link is ever valid for a given User at a
time.

### Rewards (Adult)

Manages the global Reward catalog shown to every Child — distinct from
Child Rewards, which is about redeeming, not defining. Any Adult may
manage any Reward; there is no per-Adult ownership in Telegram (who
originally created a Reward is recorded for audit purposes only).

Each Reward is fully represented by its own button — name and current
cost (💰 notation) — nothing duplicated as separate text alongside the
list. Opening one shows its full details — name, cost, and description —
with an **Edit** action. There is no Delete and no activate/deactivate
control: a Reward has no such lifecycle concept at all.

**Add Reward** and **Edit** both collect the same three fields, in the
same order:

1. name;
2. cost, in points;
3. description (optional).

Name and cost are validated the same way as everywhere else in the app
(non-blank name, positive integer cost) — invalid input is rejected with a
plain message and the Adult can simply try again. Description can always
be left blank. When editing, each prompt shows the Reward's *current*
value first, so the flow is never a surprise; skipping the description
step while editing leaves the existing description untouched rather than
erasing it.

Changing a Reward's cost only affects *future* redemptions — every
existing `RewardRedemption`'s recorded cost is a permanent historical
snapshot and is never rewritten.

### Points (Adult)

A management surface over every Child's Point ledger — distinct from
Child Points, which is a self-service balance/history view. Any Adult may
view or adjust any Child's Points; there is no per-Adult ownership in
Telegram, and there is still no permanent Adult↔Child relationship
anywhere in the product.

The Points list shows only Children, each with their current balance (💰
notation) — Adults never appear here, since there is nothing to manage
about an Adult's own Points from this screen.

Opening a Child shows their balance and recent transaction history,
newest first, paginated ("Older" loads more) — the same shape as the
Child's own Points screen, just for someone else's ledger. Each entry
shows a human-readable source and a signed amount, exactly like the
Child's own view; a manual adjustment shows the description the Adult
gave it at the time.

**Adjust points** offers two directions:

- **+ Add points** — increases the Child's balance;
- **- Remove points** — decreases it, and can never take the balance
  below zero; an attempt to remove more than the Child currently has is
  rejected outright, with no partial adjustment and no transaction
  created.

Both directions collect the same two things, in order:

1. an amount, as a positive whole number of points (the direction, not
   the number, decides the sign);
2. a description — always required, never blank. There is no way to skip
   it; a manual adjustment with no explanation is never created.

A successful adjustment shows the Child's new balance and returns to
their Points details, where the new entry is immediately visible in the
history.

### Out of scope (tracked, not yet built)

- Bulk or recurring/scheduled assignment of a Task to multiple Children.
- Task/description editing beyond title and reward points.
- Task, execution, or redemption history views (including an assignment
  history separate from the current-execution summary).
- Reward deletion or an activate/deactivate lifecycle for Rewards.
- Adult-side User editing (name, avatar) or deletion.
- Reconnecting/replacing a Telegram account already linked to a User, or
  disconnecting one — the existing activation mechanism's reconnect rules
  apply, but there is no Telegram UI for triggering them.
- Notifications, reminders, comments/reasons, attachments.
- Any Adult↔Child ownership or family-grouping concept — deliberately not
  part of this product's model.
