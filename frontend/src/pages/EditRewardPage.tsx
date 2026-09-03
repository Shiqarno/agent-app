import { useCallback, useEffect, useState } from 'react'
import { getReward, RewardNotFoundError, updateReward, type Reward } from '../api/rewards'
import RewardForm, { type RewardFormSubmitValues } from '../components/RewardForm'
import { Link, useRouter } from '../router'

type LoadState =
  | { phase: 'loading' }
  | { phase: 'loaded'; reward: Reward }
  | { phase: 'not-found' }
  | { phase: 'error'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

// The router only matches static paths (see router.tsx); the dynamic :id
// segment is read directly from the URL, the same pattern already used for
// the activation token and the task-creation return target.
function rewardIdFromPath(): string {
  return window.location.pathname.split('/')[2] ?? ''
}

function EditRewardPage() {
  const { navigate } = useRouter()
  const [rewardId] = useState(rewardIdFromPath)
  const [state, setState] = useState<LoadState>({ phase: 'loading' })

  const load = useCallback(() => {
    setState({ phase: 'loading' })
    getReward(rewardId)
      .then((reward) => setState({ phase: 'loaded', reward }))
      .catch((error: unknown) => {
        if (error instanceof RewardNotFoundError) {
          setState({ phase: 'not-found' })
        } else {
          setState({ phase: 'error', message: errorMessage(error, 'Could not load reward.') })
        }
      })
  }, [rewardId])

  useEffect(() => {
    load()
  }, [load])

  async function handleSubmit(values: RewardFormSubmitValues) {
    // Unlike creation, an empty description here must be sent as an empty
    // string, not null -- the backend's RewardUpdate treats a null field as
    // "leave unchanged", so null would silently fail to clear it.
    await updateReward(rewardId, {
      name: values.name,
      description: values.description,
      cost_points: values.cost_points,
    })
    navigate('/rewards')
  }

  return (
    <div>
      <h1>Edit reward</h1>
      {state.phase === 'loading' && <p>Loading reward...</p>}
      {state.phase === 'not-found' && (
        <p role="alert">
          Reward not found. <Link to="/rewards">Back to rewards</Link>
        </p>
      )}
      {state.phase === 'error' && (
        <p role="alert">
          {state.message} <button onClick={load}>Retry</button>{' '}
          <Link to="/rewards">Back to rewards</Link>
        </p>
      )}
      {state.phase === 'loaded' && (
        <RewardForm
          initialValues={{
            name: state.reward.name,
            description: state.reward.description ?? '',
            costPoints: String(state.reward.cost_points),
          }}
          submitLabel="Save changes"
          onSubmit={handleSubmit}
        />
      )}
    </div>
  )
}

export default EditRewardPage
