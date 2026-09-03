import { useEffect, useState } from 'react'
import { getUsers, type UserSummary } from '../api/users'
import { Link } from '../router'

type ListState =
  | { phase: 'loading' }
  | { phase: 'loaded'; users: UserSummary[] }
  | { phase: 'error'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

// A minimal read-only preview, not full User Management (out of scope for
// Issue #11) -- this is a placeholder destination for the "Users" nav entry.
function UsersPage() {
  const [state, setState] = useState<ListState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false
    getUsers()
      .then((users) => {
        if (!cancelled) setState({ phase: 'loaded', users })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ phase: 'error', message: errorMessage(error, 'Unable to load users.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div>
      <h1>Users</h1>
      <Link to="/users/new">Add user</Link>
      {state.phase === 'loading' && <p>Loading...</p>}
      {state.phase === 'error' && <p role="alert">{state.message}</p>}
      {state.phase === 'loaded' && (
        <ul>
          {state.users.map((user) => (
            <li key={user.id}>
              {user.name} ({user.role})
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default UsersPage
