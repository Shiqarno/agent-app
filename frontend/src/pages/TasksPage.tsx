import { useEffect, useState } from 'react'
import { getTasks, type Task } from '../api/tasks'
import { Link } from '../router'

type ListState =
  | { phase: 'loading' }
  | { phase: 'loaded'; tasks: Task[] }
  | { phase: 'error'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

// A minimal read-only preview, not full Task Management (out of scope for
// Issue #11) -- this is a placeholder destination for the "Tasks" nav entry.
function TasksPage() {
  const [state, setState] = useState<ListState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false
    getTasks()
      .then((tasks) => {
        if (!cancelled) setState({ phase: 'loaded', tasks })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ phase: 'error', message: errorMessage(error, 'Unable to load tasks.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div>
      <h1>Tasks</h1>
      <Link to="/tasks/new">Create task</Link>
      {state.phase === 'loading' && <p>Loading...</p>}
      {state.phase === 'error' && <p role="alert">{state.message}</p>}
      {state.phase === 'loaded' && state.tasks.length === 0 && <p>No tasks yet.</p>}
      {state.phase === 'loaded' && state.tasks.length > 0 && (
        <ul>
          {state.tasks.map((task) => (
            <li key={task.id}>
              {task.title} — {task.status}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default TasksPage
