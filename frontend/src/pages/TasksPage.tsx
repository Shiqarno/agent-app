import { useCallback, useEffect, useState } from 'react'
import { me } from '../api/auth'
import {
  claimTask,
  getTaskExecutions,
  getTasks,
  readyTaskExecution,
  startTaskExecution,
  type Task,
  type TaskExecution,
  type TaskExecutionStatus,
} from '../api/tasks'
import { Link } from '../router'

type ListState =
  | { phase: 'loading' }
  | { phase: 'loaded'; tasks: Task[]; executions: TaskExecution[] }
  | { phase: 'error'; message: string }

type ActiveFilter = 'ALL' | 'ACTIVE' | 'INACTIVE'

const ACTIVE_FILTERS: { value: ActiveFilter; label: string }[] = [
  { value: 'ALL', label: 'All' },
  { value: 'ACTIVE', label: 'Active' },
  { value: 'INACTIVE', label: 'Inactive' },
]

const STATUS_LABELS: Record<TaskExecutionStatus, string> = {
  ASSIGNED: 'Assigned',
  IN_PROGRESS: 'In progress',
  AWAITING_CONFIRMATION: 'Awaiting confirmation',
  COMPLETED: 'Completed',
  CANCELLED: 'Cancelled',
}

const EXECUTION_ACTION_LABELS: Record<'start' | 'ready', { idle: string; busy: string }> = {
  start: { idle: 'Start', busy: 'Starting...' },
  ready: { idle: 'Mark ready', busy: 'Marking ready...' },
}

// A Task with only terminal (COMPLETED/CANCELLED) executions for this Child
// is still claimable -- the backend allows unlimited historical executions
// per (task, user) and only blocks a new claim while one of these open
// statuses already exists (the same set the DB's partial unique index
// protects). Only an *open* execution should hide a Task from Available.
const OPEN_EXECUTION_STATUSES: ReadonlySet<TaskExecutionStatus> = new Set([
  'ASSIGNED',
  'IN_PROGRESS',
  'AWAITING_CONFIRMATION',
])

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function sortNewestFirst<T extends { created_at: string; id: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => {
    if (a.created_at !== b.created_at) {
      return a.created_at < b.created_at ? 1 : -1
    }
    return a.id < b.id ? 1 : -1
  })
}

type CurrentUser = { id: string; role: 'adult' | 'child' }

function AdultTaskList({ tasks }: { tasks: Task[] }) {
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>('ALL')

  const visibleTasks = sortNewestFirst(
    tasks.filter((task) => {
      if (activeFilter === 'ACTIVE') return task.is_active
      if (activeFilter === 'INACTIVE') return !task.is_active
      return true
    }),
  )

  return (
    <div>
      <div className="status-filter" role="group" aria-label="Filter by active status">
        {ACTIVE_FILTERS.map((filter) => (
          <button
            key={filter.value}
            type="button"
            aria-pressed={activeFilter === filter.value}
            onClick={() => setActiveFilter(filter.value)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {tasks.length === 0 && (
        <div>
          <p>No tasks yet.</p>
          <Link to="/tasks/new?from=tasks">Create your first task</Link>
        </div>
      )}
      {tasks.length > 0 && visibleTasks.length === 0 && <p>No tasks match this filter.</p>}
      {visibleTasks.length > 0 && (
        <ul className="task-list">
          {visibleTasks.map((task) => (
            <li key={task.id} className="task-card">
              <p className="task-card-title">{task.title}</p>
              {task.description && <p>{task.description}</p>}
              <p>Reward points: {task.reward_points}</p>
              <p>{task.is_active ? 'Active' : 'Inactive'}</p>
              <p>Created: {new Date(task.created_at).toLocaleString()}</p>
              <Link to={`/tasks/${task.id}`}>Details</Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ChildTaskLists({
  tasks,
  executions,
  onChanged,
}: {
  tasks: Task[]
  executions: TaskExecution[]
  onChanged: () => void
}) {
  const [mutatingId, setMutatingId] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const tasksById = Object.fromEntries(tasks.map((task) => [task.id, task]))
  const openExecutionTaskIds = new Set(
    executions
      .filter((execution) => OPEN_EXECUTION_STATUSES.has(execution.status))
      .map((execution) => execution.task_id),
  )
  const availableTasks = sortNewestFirst(
    tasks.filter((task) => task.is_active && !openExecutionTaskIds.has(task.id)),
  )
  const myExecutions = sortNewestFirst(executions)

  function clearError(id: string) {
    setErrors((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
  }

  async function runExecutionAction(execution: TaskExecution) {
    setMutatingId(execution.id)
    clearError(execution.id)
    try {
      if (execution.status === 'ASSIGNED') {
        await startTaskExecution(execution.id)
      } else if (execution.status === 'IN_PROGRESS') {
        await readyTaskExecution(execution.id)
      }
      onChanged()
    } catch (error) {
      setErrors((prev) => ({
        ...prev,
        [execution.id]: errorMessage(error, 'Action failed.'),
      }))
    } finally {
      setMutatingId(null)
    }
  }

  async function runClaim(task: Task) {
    setMutatingId(task.id)
    clearError(task.id)
    try {
      await claimTask(task.id)
      onChanged()
    } catch (error) {
      setErrors((prev) => ({ ...prev, [task.id]: errorMessage(error, 'Could not claim task.') }))
    } finally {
      setMutatingId(null)
    }
  }

  return (
    <div>
      <section aria-labelledby="my-tasks-heading">
        <h2 id="my-tasks-heading">My Tasks</h2>
        {myExecutions.length === 0 && <p>You haven&apos;t claimed any tasks yet.</p>}
        {myExecutions.length > 0 && (
          <ul className="task-list">
            {myExecutions.map((execution) => {
              const task = tasksById[execution.task_id]
              const action =
                execution.status === 'ASSIGNED'
                  ? 'start'
                  : execution.status === 'IN_PROGRESS'
                    ? 'ready'
                    : null
              return (
                <li key={execution.id} className="task-card">
                  <p className="task-card-title">{task?.title ?? execution.task_id}</p>
                  <p>Points: {execution.reward_points}</p>
                  <p>Status: {STATUS_LABELS[execution.status]}</p>
                  <p>Created: {new Date(execution.created_at).toLocaleString()}</p>
                  <Link to={`/tasks/${execution.task_id}`}>Details</Link>
                  {action && (
                    <button
                      onClick={() => runExecutionAction(execution)}
                      disabled={mutatingId === execution.id}
                    >
                      {mutatingId === execution.id
                        ? EXECUTION_ACTION_LABELS[action].busy
                        : EXECUTION_ACTION_LABELS[action].idle}
                    </button>
                  )}
                  {errors[execution.id] && <p role="alert">{errors[execution.id]}</p>}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section aria-labelledby="available-tasks-heading">
        <h2 id="available-tasks-heading">Available Tasks</h2>
        {availableTasks.length === 0 && <p>No tasks available to claim right now.</p>}
        {availableTasks.length > 0 && (
          <ul className="task-list">
            {availableTasks.map((task) => (
              <li key={task.id} className="task-card">
                <p className="task-card-title">{task.title}</p>
                {task.description && <p>{task.description}</p>}
                <p>Points: {task.reward_points}</p>
                <p>Created: {new Date(task.created_at).toLocaleString()}</p>
                <Link to={`/tasks/${task.id}`}>Details</Link>
                <button onClick={() => runClaim(task)} disabled={mutatingId === task.id}>
                  {mutatingId === task.id ? 'Claiming...' : 'Claim'}
                </button>
                {errors[task.id] && <p role="alert">{errors[task.id]}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function TasksPage() {
  const [state, setState] = useState<ListState>({ phase: 'loading' })
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null)

  const loadTasks = useCallback(() => {
    setState({ phase: 'loading' })
    Promise.all([getTasks(), getTaskExecutions()])
      .then(([tasks, executions]) => setState({ phase: 'loaded', tasks, executions }))
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
        // Only used to decide which view (Adult definitions vs. Child
        // My/Available Tasks) to render; falls back to loading state.
      })
  }, [])

  return (
    <div>
      <h1>Tasks</h1>
      {currentUser?.role === 'adult' && <Link to="/tasks/new?from=tasks">+ Create task</Link>}

      {state.phase === 'loading' && <p>Loading tasks...</p>}
      {state.phase === 'error' && (
        <p role="alert">
          {state.message} <button onClick={loadTasks}>Retry</button>
        </p>
      )}
      {state.phase === 'loaded' && currentUser?.role === 'adult' && (
        <AdultTaskList tasks={state.tasks} />
      )}
      {state.phase === 'loaded' && currentUser?.role === 'child' && (
        <ChildTaskLists tasks={state.tasks} executions={state.executions} onChanged={loadTasks} />
      )}
    </div>
  )
}

export default TasksPage
