import { useCallback, useEffect, useState } from 'react'
import { ApiError, getProfiles, pinLogin, type CurrentUser, type Profile } from '../api/auth'
import Avatar from '../components/Avatar'
import ErrorState from '../components/ErrorState'
import LoadingState from '../components/LoadingState'
import PinDots from '../components/PinDots'
import PinPad from '../components/PinPad'
import { Link } from '../router'

type ListState =
  | { phase: 'loading' }
  | { phase: 'loaded'; profiles: Profile[] }
  | { phase: 'error'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.code === 'TOO_MANY_ATTEMPTS') {
    return 'Too many incorrect attempts. Try again later.'
  }
  return error instanceof Error && error.message ? error.message : fallback
}

// The default /login screen (Issue #22): choose a profile, then enter a
// 4-digit PIN on a randomized keypad. Selecting a profile is local state,
// not a navigation -- there is no user id in the URL/history, and "Back"
// just clears it.
function ProfileLoginPage({ onLogin }: { onLogin: (user: CurrentUser) => void }) {
  const [state, setState] = useState<ListState>({ phase: 'loading' })
  const [selectedProfile, setSelectedProfile] = useState<Profile | null>(null)
  const [pin, setPin] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadProfiles = useCallback(() => {
    setState({ phase: 'loading' })
    getProfiles()
      .then((profiles) => setState({ phase: 'loaded', profiles }))
      .catch((err: unknown) =>
        setState({ phase: 'error', message: errorMessage(err, 'Could not load profiles.') }),
      )
  }, [])

  useEffect(() => {
    loadProfiles()
  }, [loadProfiles])

  function selectProfile(profile: Profile) {
    setSelectedProfile(profile)
    setPin('')
    setError(null)
    setAttempt((value) => value + 1)
  }

  function handleBack() {
    setSelectedProfile(null)
    setPin('')
    setError(null)
  }

  async function handleDigit(digit: string) {
    if (submitting || !selectedProfile) return
    const nextPin = pin + digit
    setPin(nextPin)
    if (nextPin.length < 4) return

    setSubmitting(true)
    setError(null)
    try {
      const user = await pinLogin(selectedProfile.id, nextPin)
      onLogin(user)
    } catch (err) {
      setError(errorMessage(err, 'Incorrect PIN.'))
      setPin('')
      setAttempt((value) => value + 1)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-page">
      <h1>Choose your profile</h1>

      {state.phase === 'loading' && <LoadingState label="Loading profiles..." />}
      {state.phase === 'error' && <ErrorState message={state.message} onRetry={loadProfiles} />}

      {state.phase === 'loaded' && !selectedProfile && (
        <>
          {state.profiles.length === 0 && <p>No profiles are available to sign in with yet.</p>}
          {state.profiles.length > 0 && (
            <ul className="profile-grid">
              {state.profiles.map((profile) => (
                <li key={profile.id}>
                  <button
                    type="button"
                    className="profile-card"
                    onClick={() => selectProfile(profile)}
                  >
                    <Avatar avatar_id={profile.avatar_id} size="lg" alt="" />
                    <span className="profile-card-name">{profile.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p>
            <Link to="/login/password">Use email and password instead</Link>
          </p>
        </>
      )}

      {state.phase === 'loaded' && selectedProfile && (
        <div className="pin-entry">
          <Avatar avatar_id={selectedProfile.avatar_id} size="lg" alt="" />
          <p className="pin-entry-name">{selectedProfile.name}</p>
          <p>Enter your PIN</p>
          <PinDots length={pin.length} />
          {error && <p role="alert">{error}</p>}
          <PinPad key={attempt} onDigit={handleDigit} disabled={submitting} />
          <button type="button" onClick={handleBack} disabled={submitting}>
            Back
          </button>
        </div>
      )}
    </div>
  )
}

export default ProfileLoginPage
