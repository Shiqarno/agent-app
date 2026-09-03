import { useCallback, useEffect, useState } from 'react'
import { getBalance } from '../api/points'
import { confirmTaskExecution, getTaskExecutions, getTasks, type Task, type TaskExecution } from '../api/tasks'
import { getUsers, type UserSummary } from '../api/users'
import { Link } from '../router'

type SectionState<T> =
  | { phase: 'loading' }
  | { phase: 'loaded'; data: T }
  | { phase: 'error'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function useTaskExecutions() {
  const [state, setState] = useState<SectionState<TaskExecution[]>>({ phase: 'loading' })

  const load = useCallback(() => {
    setState({ phase: 'loading' })
    getTaskExecutions()
      .then((executions) => setState({ phase: 'loaded', data: executions }))
      .catch((error: unknown) =>
        setState({ phase: 'error', message: errorMessage(error, 'Unable to load tasks.') }),
      )
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return { state, reload: load }
}

function useBalance() {
  const [state, setState] = useState<SectionState<number>>({ phase: 'loading' })

  const load = useCallback(() => {
    setState({ phase: 'loading' })
    getBalance()
      .then((balance) => setState({ phase: 'loaded', data: balance.balance }))
      .catch((error: unknown) =>
        setState({ phase: 'error', message: errorMessage(error, 'Unable to load points.') }),
      )
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return { state, reload: load }
}

function useUsersById() {
  const [byId, setById] = useState<Record<string, UserSummary>>({})

  useEffect(() => {
    getUsers()
      .then((users) => {
        setById(Object.fromEntries(users.map((user) => [user.id, user])))
      })
      .catch(() => {
        // Assignee names are a presentation nicety on top of the task data;
        // if this fails, sections below just fall back to the raw user id.
      })
  }, [])

  return byId
}

// A TaskExecution only carries a task_id; resolving it to a title is a
// second lookup against the Task definitions this Adult created (which is
// exactly the set every execution here belongs to, per the backend's
// visibility rules).
function useTasksById() {
  const [byId, setById] = useState<Record<string, Task>>({})

  useEffect(() => {
    getTasks()
      .then((tasks) => setById(Object.fromEntries(tasks.map((task) => [task.id, task]))))
      .catch(() => {
        // A task title is a presentation nicety on top of the execution
        // data; if this fails, sections below fall back to the raw task id.
      })
  }, [])

  return byId
}

function taskTitle(tasksById: Record<string, Task>, taskId: string): string {
  return tasksById[taskId]?.title ?? taskId
}

function assigneeLabel(usersById: Record<string, UserSummary>, userId: string): string {
  return usersById[userId]?.name ?? userId
}

function sortRecent(executions: TaskExecution[]): TaskExecution[] {
  return [...executions].sort((a, b) => {
    if (a.created_at !== b.created_at) {
      return a.created_at < b.created_at ? 1 : -1
    }
    return a.id < b.id ? 1 : -1
  })
}

function ErrorRetry({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <p role="alert">
      {message} <button onClick={onRetry}>Retry</button>
    </p>
  )
}

function PendingTasksSection({
  executionsState,
  reloadExecutions,
  reloadBalance,
  usersById,
  tasksById,
}: {
  executionsState: SectionState<TaskExecution[]>
  reloadExecutions: () => void
  reloadBalance: () => void
  usersById: Record<string, UserSummary>
  tasksById: Record<string, Task>
}) {
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [confirmErrors, setConfirmErrors] = useState<Record<string, string>>({})

  async function handleConfirm(executionId: string) {
    setConfirmingId(executionId)
    setConfirmErrors((prev) => {
      const next = { ...prev }
      delete next[executionId]
      return next
    })

    try {
      // The backend owns the AWAITING_CONFIRMATION -> COMPLETED transition
      // and the resulting TASK_COMPLETED point transaction; the dashboard
      // only triggers it and refreshes.
      await confirmTaskExecution(executionId)
      reloadExecutions()
      reloadBalance()
    } catch (error) {
      setConfirmErrors((prev) => ({
        ...prev,
        [executionId]: errorMessage(error, 'Unable to confirm this task.'),
      }))
    } finally {
      setConfirmingId(null)
    }
  }

  return (
    <section aria-labelledby="pending-tasks-heading">
      <h2 id="pending-tasks-heading">Tasks requiring attention</h2>
      {executionsState.phase === 'loading' && <p>Loading...</p>}
      {executionsState.phase === 'error' && (
        <ErrorRetry message={executionsState.message} onRetry={reloadExecutions} />
      )}
      {executionsState.phase === 'loaded' &&
        (() => {
          const pending = executionsState.data.filter(
            (execution) => execution.status === 'AWAITING_CONFIRMATION',
          )
          if (pending.length === 0) {
            return <p>No tasks waiting for confirmation.</p>
          }
          return (
            <ul>
              {pending.map((execution) => (
                <li key={execution.id}>
                  {taskTitle(tasksById, execution.task_id)} —{' '}
                  {assigneeLabel(usersById, execution.user_id)} ({execution.reward_points} pts)
                  <button
                    onClick={() => handleConfirm(execution.id)}
                    disabled={confirmingId === execution.id}
                  >
                    Confirm
                  </button>
                  {confirmErrors[execution.id] && <p role="alert">{confirmErrors[execution.id]}</p>}
                </li>
              ))}
            </ul>
          )
        })()}
    </section>
  )
}

function RecentTasksSection({
  executionsState,
  reloadExecutions,
  usersById,
  tasksById,
}: {
  executionsState: SectionState<TaskExecution[]>
  reloadExecutions: () => void
  usersById: Record<string, UserSummary>
  tasksById: Record<string, Task>
}) {
  return (
    <section aria-labelledby="recent-tasks-heading">
      <h2 id="recent-tasks-heading">Recent Tasks</h2>
      {executionsState.phase === 'loading' && <p>Loading...</p>}
      {executionsState.phase === 'error' && (
        <ErrorRetry message={executionsState.message} onRetry={reloadExecutions} />
      )}
      {executionsState.phase === 'loaded' &&
        (executionsState.data.length === 0 ? (
          <p>No tasks yet.</p>
        ) : (
          <ul>
            {sortRecent(executionsState.data)
              .slice(0, 5)
              .map((execution) => (
                <li key={execution.id}>
                  {taskTitle(tasksById, execution.task_id)} —{' '}
                  {assigneeLabel(usersById, execution.user_id)} — {execution.status}
                </li>
              ))}
          </ul>
        ))}
    </section>
  )
}

function PointsSummary({
  balanceState,
  reloadBalance,
}: {
  balanceState: SectionState<number>
  reloadBalance: () => void
}) {
  return (
    <section aria-labelledby="points-heading">
      <h2 id="points-heading">Your points</h2>
      {balanceState.phase === 'loading' && <p>Loading...</p>}
      {balanceState.phase === 'error' && (
        <ErrorRetry message={balanceState.message} onRetry={reloadBalance} />
      )}
      {balanceState.phase === 'loaded' && <p>{balanceState.data}</p>}
      <Link to="/points">View history →</Link>
    </section>
  )
}

function QuickActions() {
  return (
    <section aria-labelledby="quick-actions-heading">
      <h2 id="quick-actions-heading">Quick Actions</h2>
      <Link to="/tasks/new?from=dashboard">Create task</Link>
      <Link to="/users/new">Add user</Link>
      <Link to="/rewards/new">Create reward</Link>
    </section>
  )
}

function DashboardPage() {
  const executions = useTaskExecutions()
  const balance = useBalance()
  const usersById = useUsersById()
  const tasksById = useTasksById()

  return (
    <div>
      <h1>Dashboard</h1>
      <div className="dashboard-grid">
        <PendingTasksSection
          executionsState={executions.state}
          reloadExecutions={executions.reload}
          reloadBalance={balance.reload}
          usersById={usersById}
          tasksById={tasksById}
        />
        <RecentTasksSection
          executionsState={executions.state}
          reloadExecutions={executions.reload}
          usersById={usersById}
          tasksById={tasksById}
        />
        <PointsSummary balanceState={balance.state} reloadBalance={balance.reload} />
        <QuickActions />
      </div>
    </div>
  )
}

export default DashboardPage
