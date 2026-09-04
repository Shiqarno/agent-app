import { type FormEvent, useState } from 'react'
import { setupPin, type CurrentUser } from '../api/auth'

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

const PIN_PATTERN = /^[0-9]{4}$/

// Mandatory PIN setup for an existing, already-authenticated user who has
// never configured one (Issue #22) -- a conventional form, not the
// randomized login keypad (the spec explicitly permits and prefers this
// here). There is no skip action; the only way off this screen besides
// completing setup is logging out entirely.
function PinSetupRequiredPage({
  user,
  onComplete,
  onLogout,
}: {
  user: CurrentUser
  onComplete: (user: CurrentUser) => void
  onLogout: () => void
}) {
  const [pin, setPin] = useState('')
  const [confirmPin, setConfirmPin] = useState('')
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

    setSubmitting(true)
    try {
      const updated = await setupPin(pin)
      onComplete(updated)
    } catch (err) {
      setError(errorMessage(err, 'Could not set your PIN.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <h1>Set up your PIN</h1>
      <p>Signed in as {user.name}</p>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="new-pin">Choose a 4-digit PIN</label>
          <input
            id="new-pin"
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
          <label htmlFor="confirm-pin">Confirm your PIN</label>
          <input
            id="confirm-pin"
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={4}
            autoComplete="off"
            value={confirmPin}
            onChange={(event) => setConfirmPin(event.target.value.replace(/\D/g, ''))}
          />
        </div>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={submitting}>
          {submitting ? 'Saving...' : 'Continue'}
        </button>
      </form>
      <button type="button" onClick={onLogout}>
        Log out
      </button>
    </div>
  )
}

export default PinSetupRequiredPage
