import { useCallback, useEffect, useState } from 'react'
import { getRewards, type Reward } from '../api/rewards'
import { Link } from '../router'

type ListState =
  | { phase: 'loading' }
  | { phase: 'loaded'; rewards: Reward[] }
  | { phase: 'error'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function RewardsPage() {
  const [state, setState] = useState<ListState>({ phase: 'loading' })

  const load = useCallback(() => {
    setState({ phase: 'loading' })
    getRewards()
      .then((rewards) => setState({ phase: 'loaded', rewards }))
      .catch((error: unknown) =>
        setState({ phase: 'error', message: errorMessage(error, 'Could not load rewards.') }),
      )
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div>
      <h1>Rewards</h1>
      <Link to="/rewards/new">+ Create reward</Link>

      {state.phase === 'loading' && <p>Loading rewards...</p>}
      {state.phase === 'error' && (
        <p role="alert">
          {state.message} <button onClick={load}>Retry</button>
        </p>
      )}
      {state.phase === 'loaded' && state.rewards.length === 0 && (
        <div>
          <p>No rewards yet.</p>
          <Link to="/rewards/new">Create your first reward</Link>
        </div>
      )}
      {state.phase === 'loaded' && state.rewards.length > 0 && (
        // Rendered in the order the backend returns (name asc, id asc,
        // already deterministic) -- no client-side re-sort, per spec: an
        // API-defined ordering is respected rather than overridden.
        <ul className="reward-list">
          {state.rewards.map((reward) => (
            <li key={reward.id} className="reward-card">
              <p className="reward-card-title">{reward.name}</p>
              {reward.description && <p>{reward.description}</p>}
              <p>Cost: {reward.cost_points} points</p>
              <Link to={`/rewards/${reward.id}/edit`}>Edit</Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default RewardsPage
