import { type FormEvent, useState } from 'react'
import { login, type CurrentUser } from '../api/auth'
import { Link } from '../router'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

// The password fallback (Issue #22), reachable at /login/password -- kept
// as close as possible to the form this replaced as the default screen.
function PasswordLoginPage({ onLogin }: { onLogin: (user: CurrentUser) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)

    try {
      const user = await login(email, password)
      onLogin(user)
    } catch (err) {
      setError(errorMessage(err, 'Login failed.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <form onSubmit={handleSubmit}>
        <h1>Sign in</h1>
        <div>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>
          Sign in
        </button>
      </form>
      <p>
        <Link to="/login">Back to profile selection</Link>
      </p>
    </div>
  )
}

export default PasswordLoginPage
