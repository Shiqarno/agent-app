import { useCallback, useEffect, useState } from 'react'
import { me } from '../api/auth'
import { getBalance } from '../api/points'
import {
  confirmTask,
  getTasks,
  readyTask,
  startTask,
  type Task,
  type TaskStatus,
} from '../api/tasks'
import { getUsers, type UserSummary } from '../api/users'
import { Link } from '../router'

type ListState =
  | { phase: 'loading' }
  | { phase: 'loaded'; tasks: Task[] }
  | { phase: 'error'; message: string }

type StatusFilter = 'ALL' | TaskStatus

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'ASSIGNED', label: 'Assigned' },
  { value: 'IN_PROGRESS', label: 'In progress' },
  { value: 'AWAITING_CONFIRMATION', label: 'Awaiting confirmation' },
  { value: 'COMPLETED', label: 'Completed' },
]

const STATUS_LABELS: Record<TaskStatus, string> = {
  ASSIGNED: 'Assigned',
  IN_PROGRESS: 'In progress',
  AWAITING_CONFIRMATION: 'Awaiting confirmation',
  COMPLETED: 'Completed',
}

type ActionKind = 'start' | 'ready' | 'confirm'

const ACTION_LABELS: Record<ActionKind, { idle: string; busy: string }> = {
  start: { idle: 'Start', busy: 'Starting...' },
  ready: { idle: 'Mark ready', busy: 'Marking ready...' },
  confirm: { idle: 'Confirm', busy: 'Confirming...' },
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function sortNewestFirst(tasks: Task[]): Task[] {
  return [...tasks].sort((a, b) => {
    if (a.created_at !== b.created_at) {
      return a.created_at < b.created_at ? 1 : -1
    }
    return a.id < b.id ? 1 : -1
  })
}

function assigneeLabel(usersById: Record<string, UserSummary>, userId: string): string {
  return usersById[userId]?.name ?? userId
}

type CurrentUser = { id: string; role: 'adult' | 'child' }

// The backend remains authoritative for every transition; this only decides
// which single action button (if any) is worth *offering* to the current
// user for a given Task, based on the same visibility/ownership data the
// Task response already carries. A rejected action always surfaces the
// backend's own error -- nothing here fakes a new state.
//
// The role check on 'confirm' is a deliberate belt-and-braces addition
// (Issue #15): a Child could never actually satisfy task.created_by ===
// currentUser.id in practice, since task creation is Adult-only, but the
// rule "Child must never be offered Confirm" is explicit enough in the spec
// to assert directly rather than lean on that being true elsewhere.
function actionFor(task: Task, currentUser: CurrentUser | null): ActionKind | null {
  if (currentUser === null) return null
  if (task.status === 'ASSIGNED' && task.assigned_to === currentUser.id) return 'start'
  if (task.status === 'IN_PROGRESS' && task.assigned_to === currentUser.id) return 'ready'
  if (
    task.status === 'AWAITING_CONFIRMATION' &&
    task.created_by === currentUser.id &&
    currentUser.role === 'adult'
  ) {
    return 'confirm'
  }
  return null
}

function TasksPage() {
  const [state, setState] = useState<ListState>({ phase: 'loading' })
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null)
  const [usersById, setUsersById] = useState<Record<string, UserSummary>>({})
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL')
  const [mutatingTaskId, setMutatingTaskId] = useState<string | null>(null)
  const [mutationErrors, setMutationErrors] = useState<Record<string, string>>({})

  const loadTasks = useCallback(() => {
    setState({ phase: 'loading' })
    getTasks()
      .then((tasks) => setState({ phase: 'loaded', tasks }))
      .catch((error: unknown) =>
        setState({ phase: 'error', message: errorMessage(error, "Couldn't load tasks.") }),
      )
  }, [])

  useEffect(() => {
    loadTasks()
  }, [loadTasks])

  useEffect(() => {
    me()
      .then((user) => setCurrentUser({ id: user.id, role: user.role }))
      .catch(() => {
        // Only used to decide which action button to offer; if this fails,
        // no actions are offered (safe default -- the backend enforces
        // authorization regardless).
      })
    getUsers()
      .then((users) => setUsersById(Object.fromEntries(users.map((user) => [user.id, user]))))
      .catch(() => {
        // Assignee/creator names are a presentation nicety; falls back to
        // the raw user id if this fails.
      })
  }, [])

  async function runAction(task: Task, action: ActionKind) {
    setMutatingTaskId(task.id)
    setMutationErrors((prev) => {
      const next = { ...prev }
      delete next[task.id]
      return next
    })

    try {
      if (action === 'start') {
        await startTask(task.id)
      } else if (action === 'ready') {
        await readyTask(task.id)
      } else {
        await confirmTask(task.id)
        // Confirmation may award points; the backend owns that transaction
        // and the resulting balance -- this only refreshes it.
        getBalance().catch(() => {})
      }
      loadTasks()
    } catch (error) {
      setMutationErrors((prev) => ({ ...prev, [task.id]: errorMessage(error, 'Action failed.') }))
    } finally {
      setMutatingTaskId(null)
    }
  }

  const allTasks = state.phase === 'loaded' ? state.tasks : []
  const visibleTasks = sortNewestFirst(
    statusFilter === 'ALL' ? allTasks : allTasks.filter((task) => task.status === statusFilter),
  )

  return (
    <div>
      <h1>Tasks</h1>
      {currentUser?.role === 'adult' && <Link to="/tasks/new?from=tasks">+ Create task</Link>}

      <div className="status-filter" role="group" aria-label="Filter by status">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            aria-pressed={statusFilter === filter.value}
            onClick={() => setStatusFilter(filter.value)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {state.phase === 'loading' && <p>Loading tasks...</p>}
      {state.phase === 'error' && (
        <p role="alert">
          {state.message} <button onClick={loadTasks}>Retry</button>
        </p>
      )}
      {state.phase === 'loaded' && allTasks.length === 0 && (
        <div>
          <p>No tasks yet.</p>
          {currentUser?.role === 'adult' && (
            <Link to="/tasks/new?from=tasks">Create your first task</Link>
          )}
        </div>
      )}
      {state.phase === 'loaded' && allTasks.length > 0 && visibleTasks.length === 0 && (
        <p>No tasks match this filter.</p>
      )}
      {state.phase === 'loaded' && visibleTasks.length > 0 && (
        <ul className="task-list">
          {visibleTasks.map((task) => {
            const action = actionFor(task, currentUser)
            return (
              <li key={task.id} className="task-card">
                <p className="task-card-title">{task.title}</p>
                {task.description && <p>{task.description}</p>}
                <p>Assigned to: {assigneeLabel(usersById, task.assigned_to)}</p>
                <p>Created by: {assigneeLabel(usersById, task.created_by)}</p>
                <p>Points: {task.reward_points}</p>
                <p>Status: {STATUS_LABELS[task.status]}</p>
                <p>Created: {new Date(task.created_at).toLocaleString()}</p>
                {action && (
                  <button
                    onClick={() => runAction(task, action)}
                    disabled={mutatingTaskId === task.id}
                  >
                    {mutatingTaskId === task.id
                      ? ACTION_LABELS[action].busy
                      : ACTION_LABELS[action].idle}
                  </button>
                )}
                {mutationErrors[task.id] && <p role="alert">{mutationErrors[task.id]}</p>}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default TasksPage
