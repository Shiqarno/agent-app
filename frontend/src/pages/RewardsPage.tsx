import { useEffect, useState } from 'react'
import { getRewards, type Reward } from '../api/rewards'
import { Link } from '../router'

type ListState =
  | { phase: 'loading' }
  | { phase: 'loaded'; rewards: Reward[] }
  | { phase: 'error'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

// A minimal read-only preview, not full Reward Management (out of scope for
// Issue #11) -- this is a placeholder destination for the "Rewards" nav
// entry. The Dashboard itself does not show this catalog (Issue #11 §15).
function RewardsPage() {
  const [state, setState] = useState<ListState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false
    getRewards()
      .then((rewards) => {
        if (!cancelled) setState({ phase: 'loaded', rewards })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ phase: 'error', message: errorMessage(error, 'Unable to load rewards.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div>
      <h1>Rewards</h1>
      <Link to="/rewards/new">Create reward</Link>
      {state.phase === 'loading' && <p>Loading...</p>}
      {state.phase === 'error' && <p role="alert">{state.message}</p>}
      {state.phase === 'loaded' && state.rewards.length === 0 && <p>No rewards yet.</p>}
      {state.phase === 'loaded' && state.rewards.length > 0 && (
        <ul>
          {state.rewards.map((reward) => (
            <li key={reward.id}>
              {reward.name} — {reward.cost_points} pts
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default RewardsPage
