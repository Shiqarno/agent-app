import { type FormEvent, useEffect, useState } from 'react'
import { createTask } from '../api/tasks'
import { getUsers, type UserSummary } from '../api/users'
import { useRouter } from '../router'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function NewTaskPage() {
  const { navigate } = useRouter()
  // /tasks/new is shared by two entry points: the Dashboard's "Create task"
  // Quick Action and the Tasks page's own creation entry point. Each tags
  // its link with ?from=... so this page can return the Adult to wherever
  // they came from; read once at mount so it can't drift if the URL is
  // otherwise manipulated mid-flow (same pattern as the activation token in
  // App.tsx).
  const [returnTo] = useState<'/dashboard' | '/tasks'>(() =>
    new URLSearchParams(window.location.search).get('from') === 'dashboard'
      ? '/dashboard'
      : '/tasks',
  )
  const [users, setUsers] = useState<UserSummary[]>([])
  const [usersError, setUsersError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [assignedTo, setAssignedTo] = useState('')
  const [rewardPoints, setRewardPoints] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getUsers()
      .then((fetched) => {
        setUsers(fetched)
        if (fetched.length > 0) {
          setAssignedTo((current) => current || fetched[0].id)
        }
      })
      .catch((err: unknown) => setUsersError(errorMessage(err, 'Unable to load users.')))
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    if (!title.trim()) {
      setError('Title is required.')
      return
    }
    if (!assignedTo) {
      setError('Assignee is required.')
      return
    }
    const points = Number(rewardPoints)
    if (!Number.isInteger(points) || points <= 0) {
      setError('Reward points must be a positive whole number.')
      return
    }

    setSubmitting(true)
    try {
      // The backend remains responsible for the task lifecycle and points
      // behavior; this only calls the existing creation endpoint.
      await createTask({
        title: title.trim(),
        description: description.trim() === '' ? null : description,
        assigned_to: assignedTo,
        reward_points: points,
      })
      navigate(returnTo)
    } catch (err) {
      setError(errorMessage(err, 'Failed to create task.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <h1>Create task</h1>
      {usersError && <p role="alert">{usersError}</p>}
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="task-title">Title</label>
          <input id="task-title" value={title} onChange={(event) => setTitle(event.target.value)} />
        </div>
        <div>
          <label htmlFor="task-description">Description</label>
          <input
            id="task-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor="task-assignee">Assignee</label>
          <select
            id="task-assignee"
            value={assignedTo}
            onChange={(event) => setAssignedTo(event.target.value)}
          >
            {users.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name} ({user.role})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="task-points">Reward points</label>
          <input
            id="task-points"
            type="number"
            value={rewardPoints}
            onChange={(event) => setRewardPoints(event.target.value)}
          />
        </div>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>
          Create task
        </button>
      </form>
    </div>
  )
}

export default NewTaskPage
