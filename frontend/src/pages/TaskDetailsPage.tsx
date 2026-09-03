import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { me } from '../api/auth'
import { getBalance } from '../api/points'
import {
  ApiError,
  cancelTask,
  confirmTask,
  getTask,
  readyTask,
  reassignTask,
  startTask,
  type Task,
  type TaskStatus,
} from '../api/tasks'
import { getUsers, type UserSummary } from '../api/users'
import { Link } from '../router'

type TaskState =
  | { phase: 'loading' }
  | { phase: 'loaded'; task: Task }
  | { phase: 'not-found' }
  | { phase: 'error'; message: string }

type CurrentUser = { id: string; role: 'adult' | 'child' }

type LifecycleAction = 'start' | 'ready' | 'confirm'

const STATUS_LABELS: Record<TaskStatus, string> = {
  ASSIGNED: 'Assigned',
  IN_PROGRESS: 'In progress',
  AWAITING_CONFIRMATION: 'Awaiting confirmation',
  COMPLETED: 'Completed',
  CANCELLED: 'Cancelled',
}

const LIFECYCLE_LABELS: Record<LifecycleAction, { idle: string; busy: string }> = {
  start: { idle: 'Start', busy: 'Starting...' },
  ready: { idle: 'Mark ready', busy: 'Marking ready...' },
  confirm: { idle: 'Confirm', busy: 'Confirming...' },
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

// The router only matches static paths (see router.tsx); the dynamic :id
// segment is read directly from the URL, the same pattern already used for
// the Reward edit route and the activation token.
function taskIdFromPath(): string {
  return window.location.pathname.split('/')[2] ?? ''
}

function userLabel(usersById: Record<string, UserSummary>, userId: string): string {
  const user = usersById[userId]
  return user ? `${user.name} (${user.role})` : userId
}

type Actions = {
  canEdit: boolean
  canReassign: boolean
  canCancel: boolean
  canStart: boolean
  canMarkReady: boolean
  canConfirm: boolean
}

// The backend remains authoritative for every transition and authorization
// check; this only decides which actions are worth *offering* in the UI
// from the same creator/assignee/status data the Task response carries.
function actionsFor(task: Task, currentUser: CurrentUser | null): Actions {
  if (currentUser === null) {
    return {
      canEdit: false,
      canReassign: false,
      canCancel: false,
      canStart: false,
      canMarkReady: false,
      canConfirm: false,
    }
  }
  const isCreator = task.created_by === currentUser.id
  const isAssignee = task.assigned_to === currentUser.id
  const cancellable =
    task.status === 'ASSIGNED' ||
    task.status === 'IN_PROGRESS' ||
    task.status === 'AWAITING_CONFIRMATION'

  return {
    canEdit: isCreator && task.status === 'ASSIGNED',
    canReassign: isCreator && task.status === 'ASSIGNED',
    canCancel: isCreator && cancellable,
    canStart: isAssignee && task.status === 'ASSIGNED',
    canMarkReady: isAssignee && task.status === 'IN_PROGRESS',
    canConfirm: isCreator && task.status === 'AWAITING_CONFIRMATION' && currentUser.role === 'adult',
  }
}

function TaskDetailsPage() {
  const [taskId] = useState(taskIdFromPath)
  const [taskState, setTaskState] = useState<TaskState>({ phase: 'loading' })
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null)
  const [usersById, setUsersById] = useState<Record<string, UserSummary>>({})

  const [lifecyclePending, setLifecyclePending] = useState<LifecycleAction | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [confirmingCancel, setConfirmingCancel] = useState(false)
  const [cancelPending, setCancelPending] = useState(false)
  const [cancelError, setCancelError] = useState<string | null>(null)

  const [showReassign, setShowReassign] = useState(false)
  const [reassignTarget, setReassignTarget] = useState('')
  const [reassignPending, setReassignPending] = useState(false)
  const [reassignError, setReassignError] = useState<string | null>(null)

  const loadTask = useCallback(() => {
    setTaskState({ phase: 'loading' })
    getTask(taskId)
      .then((task) => setTaskState({ phase: 'loaded', task }))
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.code === 'TASK_NOT_FOUND') {
          setTaskState({ phase: 'not-found' })
        } else {
          setTaskState({ phase: 'error', message: errorMessage(error, 'Could not load task.') })
        }
      })
  }, [taskId])

  useEffect(() => {
    loadTask()
  }, [loadTask])

  useEffect(() => {
    me()
      .then((user) => setCurrentUser({ id: user.id, role: user.role }))
      .catch(() => {
        // Only used to decide which actions to offer; if this fails, no
        // actions are offered (safe default -- backend enforces regardless).
      })
    getUsers()
      .then((users) => setUsersById(Object.fromEntries(users.map((user) => [user.id, user]))))
      .catch(() => {
        // Creator/assignee names are a presentation nicety; falls back to
        // the raw user id if this fails.
      })
  }, [])

  async function runLifecycleAction(action: LifecycleAction) {
    setLifecyclePending(action)
    setActionError(null)
    try {
      if (action === 'start') {
        await startTask(taskId)
      } else if (action === 'ready') {
        await readyTask(taskId)
      } else {
        await confirmTask(taskId)
        // Confirmation may award points; the backend owns that transaction,
        // this only refreshes the resulting balance (not shown on this page,
        // kept fresh per the existing refresh contract from Issue #12).
        getBalance().catch(() => {})
      }
      loadTask()
    } catch (error) {
      setActionError(errorMessage(error, 'Action failed.'))
    } finally {
      setLifecyclePending(null)
    }
  }

  async function handleCancelConfirm() {
    setCancelPending(true)
    setCancelError(null)
    try {
      await cancelTask(taskId)
      setConfirmingCancel(false)
      loadTask()
    } catch (error) {
      setCancelError(errorMessage(error, 'Could not cancel this task.'))
    } finally {
      setCancelPending(false)
    }
  }

  async function handleReassignSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!reassignTarget) return

    setReassignPending(true)
    setReassignError(null)
    try {
      await reassignTask(taskId, reassignTarget)
      setShowReassign(false)
      loadTask()
    } catch (error) {
      setReassignError(errorMessage(error, 'Could not reassign this task.'))
    } finally {
      setReassignPending(false)
    }
  }

  return (
    <div>
      <Link to="/tasks">&larr; Back to tasks</Link>
      <h1>Task Details</h1>

      {taskState.phase === 'loading' && <p>Loading task...</p>}
      {taskState.phase === 'not-found' && (
        <p role="alert">
          Task not found. <Link to="/tasks">Back to tasks</Link>
        </p>
      )}
      {taskState.phase === 'error' && (
        <p role="alert">
          {taskState.message} <button onClick={loadTask}>Retry</button>
        </p>
      )}

      {taskState.phase === 'loaded' &&
        (() => {
          const task = taskState.task
          const actions = actionsFor(task, currentUser)

          return (
            <div>
              <h2>{task.title}</h2>
              {task.description && <p>{task.description}</p>}
              <p>Points: {task.reward_points}</p>
              <p>Status: {STATUS_LABELS[task.status]}</p>
              <p>Assignee: {userLabel(usersById, task.assigned_to)}</p>
              <p>Creator: {userLabel(usersById, task.created_by)}</p>
              <p>Created: {new Date(task.created_at).toLocaleString()}</p>
              <p>Updated: {new Date(task.updated_at).toLocaleString()}</p>

              {actions.canEdit && <Link to={`/tasks/${task.id}/edit`}>Edit</Link>}

              {actions.canStart && (
                <button
                  onClick={() => runLifecycleAction('start')}
                  disabled={lifecyclePending === 'start'}
                >
                  {lifecyclePending === 'start'
                    ? LIFECYCLE_LABELS.start.busy
                    : LIFECYCLE_LABELS.start.idle}
                </button>
              )}
              {actions.canMarkReady && (
                <button
                  onClick={() => runLifecycleAction('ready')}
                  disabled={lifecyclePending === 'ready'}
                >
                  {lifecyclePending === 'ready'
                    ? LIFECYCLE_LABELS.ready.busy
                    : LIFECYCLE_LABELS.ready.idle}
                </button>
              )}
              {actions.canConfirm && (
                <button
                  onClick={() => runLifecycleAction('confirm')}
                  disabled={lifecyclePending === 'confirm'}
                >
                  {lifecyclePending === 'confirm'
                    ? LIFECYCLE_LABELS.confirm.busy
                    : LIFECYCLE_LABELS.confirm.idle}
                </button>
              )}
              {actionError && <p role="alert">{actionError}</p>}

              {actions.canReassign && (
                <div>
                  {!showReassign && (
                    <button onClick={() => setShowReassign(true)}>Reassign</button>
                  )}
                  {showReassign && (
                    <form onSubmit={handleReassignSubmit}>
                      <label htmlFor="reassign-target">New assignee</label>
                      <select
                        id="reassign-target"
                        value={reassignTarget}
                        onChange={(event) => setReassignTarget(event.target.value)}
                      >
                        <option value="">Select a user</option>
                        {Object.values(usersById).map((user) => (
                          <option key={user.id} value={user.id}>
                            {user.name} ({user.role})
                          </option>
                        ))}
                      </select>
                      {reassignError && <p role="alert">{reassignError}</p>}
                      <button
                        type="button"
                        onClick={() => setShowReassign(false)}
                        disabled={reassignPending}
                      >
                        Cancel
                      </button>
                      <button type="submit" disabled={reassignPending || !reassignTarget}>
                        {reassignPending ? 'Reassigning...' : 'Save'}
                      </button>
                    </form>
                  )}
                </div>
              )}

              {actions.canCancel && (
                <div>
                  {!confirmingCancel && (
                    <button onClick={() => setConfirmingCancel(true)}>Cancel task</button>
                  )}
                  {confirmingCancel && (
                    <div>
                      <p>Cancel &quot;{task.title}&quot;? This cannot be undone.</p>
                      <button
                        onClick={() => setConfirmingCancel(false)}
                        disabled={cancelPending}
                      >
                        Keep task
                      </button>
                      <button onClick={handleCancelConfirm} disabled={cancelPending}>
                        {cancelPending ? 'Cancelling...' : 'Cancel task'}
                      </button>
                      {cancelError && <p role="alert">{cancelError}</p>}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })()}
    </div>
  )
}

export default TaskDetailsPage
