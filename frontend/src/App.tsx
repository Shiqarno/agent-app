import { type FormEvent, useEffect, useState } from 'react'
import { activate, login, logout, me, type CurrentUser } from './api/auth'
import ProjectsPage from './ProjectsPage'

type AuthState =
  | { phase: 'loading' }
  | { phase: 'anonymous' }
  | { phase: 'authenticated'; user: CurrentUser }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function LoginForm({ onLogin }: { onLogin: (user: CurrentUser) => void }) {
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
  )
}

function ActivationForm({
  token,
  onActivated,
}: {
  token: string
  onActivated: (user: CurrentUser) => void
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)

    try {
      const user = await activate(token, email, password)
      onActivated(user)
    } catch (err) {
      setError(errorMessage(err, 'Activation failed.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <h1>Activate your account</h1>
      <div>
        <label htmlFor="activation-email">Email</label>
        <input
          id="activation-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div>
        <label htmlFor="activation-password">Password</label>
        <input
          id="activation-password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={submitting}>
        Activate
      </button>
    </form>
  )
}

function App() {
  const [auth, setAuth] = useState<AuthState>({ phase: 'loading' })
  // The activation link (POST /api/users creates this token server-side, out
  // of band -- Issue #10) carries the token as a URL query parameter. It is
  // read once and never persisted client-side (no localStorage), matching
  // the same "never store a raw token" discipline as the session cookie.
  const [activationToken] = useState(() =>
    new URLSearchParams(window.location.search).get('activation_token'),
  )

  useEffect(() => {
    let cancelled = false

    me()
      .then((user) => {
        if (!cancelled) {
          setAuth({ phase: 'authenticated', user })
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAuth({ phase: 'anonymous' })
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  async function handleLogout() {
    try {
      await logout()
    } finally {
      setAuth({ phase: 'anonymous' })
    }
  }

  if (auth.phase === 'loading') {
    return <p>Loading...</p>
  }

  if (auth.phase === 'anonymous') {
    if (activationToken) {
      return (
        <ActivationForm
          token={activationToken}
          onActivated={(user) => setAuth({ phase: 'authenticated', user })}
        />
      )
    }
    return <LoginForm onLogin={(user) => setAuth({ phase: 'authenticated', user })} />
  }

  return (
    <>
      <p>
        Signed in as {auth.user.name} ({auth.user.role})
        <button onClick={handleLogout}>Log out</button>
      </p>
      <ProjectsPage />
    </>
  )
}

export default App
