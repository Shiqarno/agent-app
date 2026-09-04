import { useCallback, useEffect, useState } from 'react'
import {
  activationUrlFor,
  ApiError,
  getUsers,
  regenerateActivation,
  type ActivationStatus,
  type UserSummary,
} from '../api/users'
import Avatar from '../components/Avatar'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import LoadingState from '../components/LoadingState'
import PageHeader from '../components/PageHeader'
import { Link } from '../router'

type ListState =
  | { phase: 'loading' }
  | { phase: 'loaded'; users: UserSummary[] }
  | { phase: 'error'; message: string }

type RegenerationState =
  | { phase: 'idle' }
  | { phase: 'pending' }
  | { phase: 'success'; activationUrl: string; expiresAt: string }
  | { phase: 'error'; message: string }

type CopyStatus = 'idle' | 'copied' | 'failed'

const ACTIVATION_STATUS_LABELS: Record<ActivationStatus, string> = {
  ACTIVE: 'Active',
  PENDING: 'Pending activation',
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function UsersPage() {
  const [state, setState] = useState<ListState>({ phase: 'loading' })
  const [regenerations, setRegenerations] = useState<Record<string, RegenerationState>>({})
  const [copyStatuses, setCopyStatuses] = useState<Record<string, CopyStatus>>({})

  const loadUsers = useCallback(() => {
    setState({ phase: 'loading' })
    getUsers()
      .then((users) => setState({ phase: 'loaded', users }))
      .catch((error: unknown) =>
        setState({ phase: 'error', message: errorMessage(error, 'Unable to load users.') }),
      )
  }, [])

  useEffect(() => {
    loadUsers()
  }, [loadUsers])

  async function handleGenerate(userId: string) {
    setRegenerations((prev) => ({ ...prev, [userId]: { phase: 'pending' } }))
    setCopyStatuses((prev) => ({ ...prev, [userId]: 'idle' }))

    try {
      // The backend owns token generation, hashing, storage, and TTL; this
      // only calls the endpoint and reacts to the result -- no local state
      // change is assumed until the request actually succeeds.
      const response = await regenerateActivation(userId)
      setRegenerations((prev) => ({
        ...prev,
        [userId]: {
          phase: 'success',
          activationUrl: activationUrlFor(response.activation_token),
          expiresAt: response.expires_at,
        },
      }))
    } catch (error) {
      if (error instanceof ApiError && error.code === 'USER_ALREADY_ACTIVATED') {
        // The status shown was stale (the user activated in the meantime);
        // refresh the list so it reflects that rather than leaving a
        // Generate action visible for a User who is now ACTIVE.
        setRegenerations((prev) => ({ ...prev, [userId]: { phase: 'idle' } }))
        loadUsers()
        return
      }
      setRegenerations((prev) => ({
        ...prev,
        [userId]: { phase: 'error', message: errorMessage(error, 'Could not generate a link.') },
      }))
    }
  }

  async function handleCopy(userId: string, activationUrl: string) {
    try {
      await navigator.clipboard.writeText(activationUrl)
      setCopyStatuses((prev) => ({ ...prev, [userId]: 'copied' }))
    } catch {
      setCopyStatuses((prev) => ({ ...prev, [userId]: 'failed' }))
    }
  }

  return (
    <div>
      <PageHeader title="Users" action={<Link to="/users/new">Add user</Link>} />

      {state.phase === 'loading' && <LoadingState label="Loading users..." />}
      {state.phase === 'error' && <ErrorState message={state.message} onRetry={loadUsers} />}
      {state.phase === 'loaded' && state.users.length === 0 && (
        <EmptyState message="No users yet." />
      )}
      {state.phase === 'loaded' && state.users.length > 0 && (
        <ul className="user-list">
          {state.users.map((user) => {
            const regeneration = regenerations[user.id] ?? { phase: 'idle' }
            return (
              <li key={user.id} className="user-card">
                <Avatar avatar_id={user.avatar_id} size="sm" alt={`${user.name}'s avatar`} />
                <p className="user-card-title">{user.name}</p>
                <p>Role: {user.role}</p>
                <p>
                  Status:{' '}
                  <Badge tone={user.activation_status === 'ACTIVE' ? 'success' : 'warning'}>
                    {ACTIVATION_STATUS_LABELS[user.activation_status]}
                  </Badge>
                </p>

                {user.activation_status === 'PENDING' && (
                  <div>
                    <button
                      onClick={() => handleGenerate(user.id)}
                      disabled={regeneration.phase === 'pending'}
                    >
                      {regeneration.phase === 'pending'
                        ? 'Generating...'
                        : 'Generate activation link'}
                    </button>
                    {regeneration.phase === 'error' && (
                      <p role="alert">{regeneration.message}</p>
                    )}
                    {regeneration.phase === 'success' && (
                      <div>
                        <p>
                          <code>{regeneration.activationUrl}</code>
                        </p>
                        <p>
                          Expires: {new Date(regeneration.expiresAt).toLocaleString()}
                        </p>
                        <button
                          onClick={() => handleCopy(user.id, regeneration.activationUrl)}
                        >
                          Copy link
                        </button>
                        {copyStatuses[user.id] === 'copied' && <p role="status">Copied.</p>}
                        {copyStatuses[user.id] === 'failed' && (
                          <p role="alert">Could not copy automatically.</p>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default UsersPage
