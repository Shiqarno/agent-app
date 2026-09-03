import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { ApiError, getTask, updateTask, type Task } from '../api/tasks'
import { Link, useRouter } from '../router'

type LoadState =
  | { phase: 'loading' }
  | { phase: 'loaded'; task: Task }
  | { phase: 'not-found' }
  | { phase: 'error'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

// The router only matches static paths (see router.tsx); the dynamic :id
// segment is read directly from the URL, the same pattern already used for
// the Reward edit route and the activation token.
function taskIdFromPath(): string {
  return window.location.pathname.split('/')[2] ?? ''
}

function EditTaskPage() {
  const { navigate } = useRouter()
  const [taskId] = useState(taskIdFromPath)
  const [state, setState] = useState<LoadState>({ phase: 'loading' })
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setState({ phase: 'loading' })
    getTask(taskId)
      .then((task) => {
        setState({ phase: 'loaded', task })
        setTitle(task.title)
        setDescription(task.description ?? '')
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.code === 'TASK_NOT_FOUND') {
          setState({ phase: 'not-found' })
        } else {
          setState({ phase: 'error', message: errorMessage(err, 'Could not load task.') })
        }
      })
  }, [taskId])

  useEffect(() => {
    load()
  }, [load])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!title.trim()) {
      setError('Title is required.')
      return
    }

    setError(null)
    setSubmitting(true)
    try {
      // Only title/description are editable here -- reward points, status,
      // and assignment each have their own dedicated flow (Reassign, the
      // lifecycle actions) and are never sent from this form.
      await updateTask(taskId, { title: title.trim(), description })
      navigate(`/tasks/${taskId}`)
    } catch (err) {
      setError(errorMessage(err, 'Could not save changes.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <h1>Edit task</h1>

      {state.phase === 'loading' && <p>Loading task...</p>}
      {state.phase === 'not-found' && (
        <p role="alert">
          Task not found. <Link to="/tasks">Back to tasks</Link>
        </p>
      )}
      {state.phase === 'error' && (
        <p role="alert">
          {state.message} <button onClick={load}>Retry</button>
        </p>
      )}
      {state.phase === 'loaded' && (
        <form onSubmit={handleSubmit}>
          <div>
            <label htmlFor="task-edit-title">Title</label>
            <input
              id="task-edit-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div>
            <label htmlFor="task-edit-description">Description</label>
            <input
              id="task-edit-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          {error && <p role="alert">{error}</p>}
          <button type="submit" disabled={submitting}>
            {submitting ? 'Saving...' : 'Save'}
          </button>
          <Link to={`/tasks/${taskId}`}>Cancel</Link>
        </form>
      )}
    </div>
  )
}

export default EditTaskPage
