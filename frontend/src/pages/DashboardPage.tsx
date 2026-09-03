import { useCallback, useEffect, useState } from 'react'
import { getBalance } from '../api/points'
import { confirmTask, getTasks, type Task } from '../api/tasks'
import { getUsers, type UserSummary } from '../api/users'
import { Link } from '../router'

type SectionState<T> =
  | { phase: 'loading' }
  | { phase: 'loaded'; data: T }
  | { phase: 'error'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function useTasks() {
  const [state, setState] = useState<SectionState<Task[]>>({ phase: 'loading' })

  const load = useCallback(() => {
    setState({ phase: 'loading' })
    getTasks()
      .then((tasks) => setState({ phase: 'loaded', data: tasks }))
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

function assigneeLabel(usersById: Record<string, UserSummary>, userId: string): string {
  return usersById[userId]?.name ?? userId
}

function sortRecent(tasks: Task[]): Task[] {
  return [...tasks].sort((a, b) => {
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
  tasksState,
  reloadTasks,
  reloadBalance,
  usersById,
}: {
  tasksState: SectionState<Task[]>
  reloadTasks: () => void
  reloadBalance: () => void
  usersById: Record<string, UserSummary>
}) {
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [confirmErrors, setConfirmErrors] = useState<Record<string, string>>({})

  async function handleConfirm(taskId: string) {
    setConfirmingId(taskId)
    setConfirmErrors((prev) => {
      const next = { ...prev }
      delete next[taskId]
      return next
    })

    try {
      // The backend owns the AWAITING_CONFIRMATION -> COMPLETED transition
      // and the resulting TASK_COMPLETED point transaction; the dashboard
      // only triggers it and refreshes.
      await confirmTask(taskId)
      reloadTasks()
      reloadBalance()
    } catch (error) {
      setConfirmErrors((prev) => ({
        ...prev,
        [taskId]: errorMessage(error, 'Unable to confirm this task.'),
      }))
    } finally {
      setConfirmingId(null)
    }
  }

  return (
    <section aria-labelledby="pending-tasks-heading">
      <h2 id="pending-tasks-heading">Tasks requiring attention</h2>
      {tasksState.phase === 'loading' && <p>Loading...</p>}
      {tasksState.phase === 'error' && (
        <ErrorRetry message={tasksState.message} onRetry={reloadTasks} />
      )}
      {tasksState.phase === 'loaded' &&
        (() => {
          const pending = tasksState.data.filter((task) => task.status === 'AWAITING_CONFIRMATION')
          if (pending.length === 0) {
            return <p>No tasks waiting for confirmation.</p>
          }
          return (
            <ul>
              {pending.map((task) => (
                <li key={task.id}>
                  {task.title} — {assigneeLabel(usersById, task.assigned_to)} ({task.reward_points}{' '}
                  pts)
                  <button onClick={() => handleConfirm(task.id)} disabled={confirmingId === task.id}>
                    Confirm
                  </button>
                  {confirmErrors[task.id] && <p role="alert">{confirmErrors[task.id]}</p>}
                </li>
              ))}
            </ul>
          )
        })()}
    </section>
  )
}

function RecentTasksSection({
  tasksState,
  reloadTasks,
  usersById,
}: {
  tasksState: SectionState<Task[]>
  reloadTasks: () => void
  usersById: Record<string, UserSummary>
}) {
  return (
    <section aria-labelledby="recent-tasks-heading">
      <h2 id="recent-tasks-heading">Recent Tasks</h2>
      {tasksState.phase === 'loading' && <p>Loading...</p>}
      {tasksState.phase === 'error' && (
        <ErrorRetry message={tasksState.message} onRetry={reloadTasks} />
      )}
      {tasksState.phase === 'loaded' &&
        (tasksState.data.length === 0 ? (
          <p>No tasks yet.</p>
        ) : (
          <ul>
            {sortRecent(tasksState.data)
              .slice(0, 5)
              .map((task) => (
                <li key={task.id}>
                  {task.title} — {assigneeLabel(usersById, task.assigned_to)} — {task.status}
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
      <Link to="/tasks/new">Create task</Link>
      <Link to="/users/new">Add user</Link>
      <Link to="/rewards/new">Create reward</Link>
    </section>
  )
}

function DashboardPage() {
  const tasks = useTasks()
  const balance = useBalance()
  const usersById = useUsersById()

  return (
    <div>
      <h1>Dashboard</h1>
      <div className="dashboard-grid">
        <PendingTasksSection
          tasksState={tasks.state}
          reloadTasks={tasks.reload}
          reloadBalance={balance.reload}
          usersById={usersById}
        />
        <RecentTasksSection
          tasksState={tasks.state}
          reloadTasks={tasks.reload}
          usersById={usersById}
        />
        <PointsSummary balanceState={balance.state} reloadBalance={balance.reload} />
        <QuickActions />
      </div>
    </div>
  )
}

export default DashboardPage
