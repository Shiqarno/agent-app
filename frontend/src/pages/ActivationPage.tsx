import { type FormEvent, useState } from 'react'
import { activate, type CurrentUser } from '../api/auth'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

const PIN_PATTERN = /^[0-9]{4}$/

// PIN is now the primary credential (Issue #22); password is an optional
// alternative sign-in method, not required, and not confirmed unless one
// was actually entered.
function ActivationPage({
  token,
  onActivated,
}: {
  token: string
  onActivated: (user: CurrentUser) => void
}) {
  const [email, setEmail] = useState('')
  const [pin, setPin] = useState('')
  const [confirmPin, setConfirmPin] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    if (!PIN_PATTERN.test(pin)) {
      setError('PIN must be exactly 4 digits.')
      return
    }
    if (pin !== confirmPin) {
      setError('PINs do not match.')
      return
    }
    if (password && password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setSubmitting(true)
    try {
      const user = await activate(token, email, pin, password || undefined)
      onActivated(user)
    } catch (err) {
      setError(errorMessage(err, 'Activation failed.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
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
          <label htmlFor="activation-pin">PIN</label>
          <input
            id="activation-pin"
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={4}
            autoComplete="off"
            value={pin}
            onChange={(event) => setPin(event.target.value.replace(/\D/g, ''))}
          />
        </div>
        <div>
          <label htmlFor="activation-confirm-pin">Confirm PIN</label>
          <input
            id="activation-confirm-pin"
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={4}
            autoComplete="off"
            value={confirmPin}
            onChange={(event) => setConfirmPin(event.target.value.replace(/\D/g, ''))}
          />
        </div>
        <p>Password is optional -- an alternative way to sign in besides your PIN.</p>
        <div>
          <label htmlFor="activation-password">Password (optional)</label>
          <input
            id="activation-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        <div>
          <label htmlFor="activation-confirm-password">Confirm password</label>
          <input
            id="activation-confirm-password"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
          />
        </div>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>
          Activate
        </button>
      </form>
    </div>
  )
}

export default ActivationPage
