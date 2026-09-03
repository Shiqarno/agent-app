import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { me } from '../api/auth'
import { getBalance } from '../api/points'
import {
  ApiError,
  cancelTaskExecution,
  claimTask,
  confirmTaskExecution,
  getTask,
  getTaskExecutions,
  readyTaskExecution,
  reassignTaskExecution,
  startTaskExecution,
  type Task,
  type TaskExecution,
  type TaskExecutionStatus,
} from '../api/tasks'
import { getUsers, type UserSummary } from '../api/users'
import { Link } from '../router'

type TaskState =
  | { phase: 'loading' }
  | { phase: 'loaded'; task: Task }
  | { phase: 'not-found' }
  | { phase: 'error'; message: string }

type CurrentUser = { id: string; role: 'adult' | 'child' }

const STATUS_LABELS: Record<TaskExecutionStatus, string> = {
  ASSIGNED: 'Assigned',
  IN_PROGRESS: 'In progress',
  AWAITING_CONFIRMATION: 'Awaiting confirmation',
  COMPLETED: 'Completed',
  CANCELLED: 'Cancelled',
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

// One row in the creator's execution list. Each execution has its own
// pending/error/confirm-step state (not a single page-wide one) since a
// creator may be acting on several executions of the same Task.
function ExecutionRow({
  execution,
  usersById,
  onChanged,
}: {
  execution: TaskExecution
  usersById: Record<string, UserSummary>
  onChanged: () => void
}) {
  const [pending, setPending] = useState<'confirm' | 'cancel' | 'reassign' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmingCancel, setConfirmingCancel] = useState(false)
  const [showReassign, setShowReassign] = useState(false)
  const [reassignTarget, setReassignTarget] = useState('')

  async function handleConfirm() {
    setPending('confirm')
    setError(null)
    try {
      await confirmTaskExecution(execution.id)
      // Confirmation may award points; the backend owns that transaction
      // and the resulting balance -- this only refreshes it.
      getBalance().catch(() => {})
      onChanged()
    } catch (err) {
      setError(errorMessage(err, 'Could not confirm this task.'))
      setPending(null)
    }
  }

  async function handleCancel() {
    setPending('cancel')
    setError(null)
    try {
      await cancelTaskExecution(execution.id)
      setConfirmingCancel(false)
      onChanged()
    } catch (err) {
      setError(errorMessage(err, 'Could not cancel this task.'))
      setPending(null)
    }
  }

  async function handleReassignSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!reassignTarget) return
    setPending('reassign')
    setError(null)
    try {
      await reassignTaskExecution(execution.id, reassignTarget)
      setShowReassign(false)
      onChanged()
    } catch (err) {
      setError(errorMessage(err, 'Could not reassign this task.'))
      setPending(null)
    }
  }

  const cancellable =
    execution.status === 'ASSIGNED' ||
    execution.status === 'IN_PROGRESS' ||
    execution.status === 'AWAITING_CONFIRMATION'

  return (
    <li className="execution-card">
      <p>Assignee: {userLabel(usersById, execution.user_id)}</p>
      <p>Status: {STATUS_LABELS[execution.status]}</p>
      <p>Points: {execution.reward_points}</p>
      <p>Created: {new Date(execution.created_at).toLocaleString()}</p>

      {execution.status === 'AWAITING_CONFIRMATION' && (
        <button onClick={handleConfirm} disabled={pending !== null}>
          {pending === 'confirm' ? 'Confirming...' : 'Confirm'}
        </button>
      )}

      {execution.status === 'ASSIGNED' && (
        <div>
          {!showReassign && (
            <button onClick={() => setShowReassign(true)} disabled={pending !== null}>
              Reassign
            </button>
          )}
          {showReassign && (
            <form onSubmit={handleReassignSubmit}>
              <label htmlFor={`reassign-target-${execution.id}`}>New assignee</label>
              <select
                id={`reassign-target-${execution.id}`}
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
              <button
                type="button"
                onClick={() => setShowReassign(false)}
                disabled={pending !== null}
              >
                Cancel
              </button>
              <button type="submit" disabled={pending !== null || !reassignTarget}>
                {pending === 'reassign' ? 'Reassigning...' : 'Save'}
              </button>
            </form>
          )}
        </div>
      )}

      {cancellable && (
        <div>
          {!confirmingCancel && (
            <button onClick={() => setConfirmingCancel(true)} disabled={pending !== null}>
              Cancel task
            </button>
          )}
          {confirmingCancel && (
            <div>
              <p>Cancel this execution? This cannot be undone.</p>
              <button onClick={() => setConfirmingCancel(false)} disabled={pending !== null}>
                Keep task
              </button>
              <button onClick={handleCancel} disabled={pending !== null}>
                {pending === 'cancel' ? 'Cancelling...' : 'Cancel task'}
              </button>
            </div>
          )}
        </div>
      )}

      {error && <p role="alert">{error}</p>}
    </li>
  )
}

function TaskDetailsPage() {
  const [taskId] = useState(taskIdFromPath)
  const [taskState, setTaskState] = useState<TaskState>({ phase: 'loading' })
  const [executions, setExecutions] = useState<TaskExecution[]>([])
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null)
  const [usersById, setUsersById] = useState<Record<string, UserSummary>>({})

  const [ownActionPending, setOwnActionPending] = useState(false)
  const [ownActionError, setOwnActionError] = useState<string | null>(null)
  const [claimPending, setClaimPending] = useState(false)
  const [claimError, setClaimError] = useState<string | null>(null)

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

  const loadExecutions = useCallback(() => {
    getTaskExecutions()
      .then((all) => setExecutions(all.filter((execution) => execution.task_id === taskId)))
      .catch(() => {
        // Executions are only used to enrich this page (creator's list,
        // Child's own status/claim eligibility); if this fails, the page
        // still shows the Task itself.
      })
  }, [taskId])

  useEffect(() => {
    loadTask()
  }, [loadTask])

  useEffect(() => {
    loadExecutions()
  }, [loadExecutions])

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

  function refreshAfterMutation() {
    loadTask()
    loadExecutions()
  }

  async function handleClaim() {
    setClaimPending(true)
    setClaimError(null)
    try {
      await claimTask(taskId)
      refreshAfterMutation()
    } catch (error) {
      setClaimError(errorMessage(error, 'Could not claim this task.'))
    } finally {
      setClaimPending(false)
    }
  }

  async function handleOwnAction(executionId: string, action: 'start' | 'ready') {
    setOwnActionPending(true)
    setOwnActionError(null)
    try {
      if (action === 'start') {
        await startTaskExecution(executionId)
      } else {
        await readyTaskExecution(executionId)
      }
      refreshAfterMutation()
    } catch (error) {
      setOwnActionError(errorMessage(error, 'Action failed.'))
    } finally {
      setOwnActionPending(false)
    }
  }

  const isCreator =
    taskState.phase === 'loaded' &&
    currentUser !== null &&
    taskState.task.created_by === currentUser.id
  const ownExecution =
    currentUser !== null
      ? (executions.find((execution) => execution.user_id === currentUser.id) ?? null)
      : null

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

          return (
            <div>
              <h2>{task.title}</h2>
              {task.description && <p>{task.description}</p>}
              <p>Reward points: {task.reward_points}</p>
              <p>{task.is_active ? 'Active' : 'Inactive'}</p>
              <p>Creator: {userLabel(usersById, task.created_by)}</p>
              <p>Created: {new Date(task.created_at).toLocaleString()}</p>
              <p>Updated: {new Date(task.updated_at).toLocaleString()}</p>

              {isCreator && (
                <div>
                  <Link to={`/tasks/${task.id}/edit`}>Edit</Link>

                  <h3>Executions</h3>
                  {executions.length === 0 && <p>No one has claimed this task yet.</p>}
                  {executions.length > 0 && (
                    <ul>
                      {executions.map((execution) => (
                        <ExecutionRow
                          key={execution.id}
                          execution={execution}
                          usersById={usersById}
                          onChanged={refreshAfterMutation}
                        />
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {!isCreator && currentUser !== null && (
                <div>
                  {ownExecution && (
                    <div>
                      <p>Your status: {STATUS_LABELS[ownExecution.status]}</p>
                      {ownExecution.status === 'ASSIGNED' && (
                        <button
                          onClick={() => handleOwnAction(ownExecution.id, 'start')}
                          disabled={ownActionPending}
                        >
                          {ownActionPending ? 'Starting...' : 'Start'}
                        </button>
                      )}
                      {ownExecution.status === 'IN_PROGRESS' && (
                        <button
                          onClick={() => handleOwnAction(ownExecution.id, 'ready')}
                          disabled={ownActionPending}
                        >
                          {ownActionPending ? 'Marking ready...' : 'Mark ready'}
                        </button>
                      )}
                      {ownActionError && <p role="alert">{ownActionError}</p>}
                    </div>
                  )}
                  {!ownExecution && task.is_active && (
                    <div>
                      <button onClick={handleClaim} disabled={claimPending}>
                        {claimPending ? 'Claiming...' : 'Claim task'}
                      </button>
                      {claimError && <p role="alert">{claimError}</p>}
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
