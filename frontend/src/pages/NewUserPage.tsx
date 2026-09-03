import { type FormEvent, useState } from 'react'
import { activationUrlFor, createUser, type UserRole } from '../api/users'
import { useRouter } from '../router'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

type CreatedUser = {
  name: string
  activationUrl: string
}

function NewUserPage() {
  const { navigate } = useRouter()
  const [name, setName] = useState('')
  const [role, setRole] = useState<UserRole>('child')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<CreatedUser | null>(null)
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!name.trim()) {
      setError('Name is required.')
      return
    }

    setError(null)
    setSubmitting(true)
    try {
      const user = await createUser({ name: name.trim(), role })
      setCreated({ name: user.name, activationUrl: activationUrlFor(user.activation_token) })
    } catch (err) {
      setError(errorMessage(err, 'Failed to create user.'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleCopy() {
    if (!created) return
    try {
      await navigator.clipboard.writeText(created.activationUrl)
      setCopyStatus('copied')
    } catch {
      setCopyStatus('failed')
    }
  }

  if (created) {
    return (
      <div>
        <h1>User created</h1>
        <p>
          Share this activation link with {created.name} -- it is shown only once. Delivering it
          (e.g. by email) is not handled by this application yet.
        </p>
        <p>
          <code>{created.activationUrl}</code>
        </p>
        <button onClick={handleCopy}>Copy link</button>
        {copyStatus === 'copied' && <p role="status">Copied.</p>}
        {copyStatus === 'failed' && <p role="alert">Could not copy automatically.</p>}
        <button onClick={() => navigate('/dashboard')}>Back to Dashboard</button>
      </div>
    )
  }

  return (
    <div>
      <h1>Add user</h1>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="new-user-name">Name</label>
          <input
            id="new-user-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor="new-user-role">Role</label>
          <select
            id="new-user-role"
            value={role}
            onChange={(event) => setRole(event.target.value as UserRole)}
          >
            <option value="adult">Adult</option>
            <option value="child">Child</option>
          </select>
        </div>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>
          Add user
        </button>
      </form>
    </div>
  )
}

export default NewUserPage
