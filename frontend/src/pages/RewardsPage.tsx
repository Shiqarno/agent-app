import { useCallback, useEffect, useState } from 'react'
import { me } from '../api/auth'
import { getBalance, getHistory } from '../api/points'
import { getRewards, redeemReward, type Reward } from '../api/rewards'
import { Link } from '../router'

type ListState<T> =
  | { phase: 'loading' }
  | { phase: 'loaded'; data: T }
  | { phase: 'error'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function RewardsPage() {
  const [rewardsState, setRewardsState] = useState<ListState<Reward[]>>({ phase: 'loading' })
  const [balanceState, setBalanceState] = useState<ListState<number>>({ phase: 'loading' })
  const [currentRole, setCurrentRole] = useState<'adult' | 'child' | null>(null)

  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [redeemingId, setRedeemingId] = useState<string | null>(null)
  const [redemptionErrors, setRedemptionErrors] = useState<Record<string, string>>({})
  const [redemptionSuccess, setRedemptionSuccess] = useState<{
    rewardId: string
    message: string
  } | null>(null)

  const loadRewards = useCallback(() => {
    setRewardsState({ phase: 'loading' })
    getRewards()
      .then((rewards) => setRewardsState({ phase: 'loaded', data: rewards }))
      .catch((error: unknown) =>
        setRewardsState({ phase: 'error', message: errorMessage(error, 'Could not load rewards.') }),
      )
  }, [])

  const loadBalance = useCallback(() => {
    setBalanceState({ phase: 'loading' })
    // Informational display only -- the backend remains the sole source of
    // truth for balance and re-validates it authoritatively on redemption.
    getBalance()
      .then((balance) => setBalanceState({ phase: 'loaded', data: balance.balance }))
      .catch((error: unknown) =>
        setBalanceState({ phase: 'error', message: errorMessage(error, 'Could not load balance.') }),
      )
  }, [])

  useEffect(() => {
    loadRewards()
  }, [loadRewards])

  useEffect(() => {
    loadBalance()
  }, [loadBalance])

  useEffect(() => {
    me()
      .then((user) => setCurrentRole(user.role))
      .catch(() => {
        // Only used to decide whether to show Edit; if this fails, Edit is
        // simply not offered (safe default -- backend authorization is the
        // real enforcement regardless).
      })
  }, [])

  function startRedeeming(rewardId: string) {
    setConfirmingId(rewardId)
    setRedemptionSuccess(null)
    setRedemptionErrors((prev) => {
      const next = { ...prev }
      delete next[rewardId]
      return next
    })
  }

  function cancelRedeeming() {
    setConfirmingId(null)
  }

  async function confirmRedeem(reward: Reward) {
    setRedeemingId(reward.id)
    try {
      // The backend performs the atomic RewardRedemption + PointTransaction
      // write and re-validates the balance itself; this only calls it and
      // reacts to the result -- no local balance math, no optimistic update.
      await redeemReward(reward.id)
      setConfirmingId(null)
      setRedemptionSuccess({ rewardId: reward.id, message: `Redeemed "${reward.name}".` })
      loadBalance()
      // Not displayed on this page, but kept fresh per the refresh contract
      // (the Points page reloads its own history on mount regardless).
      getHistory().catch(() => {})
    } catch (error) {
      setRedemptionErrors((prev) => ({
        ...prev,
        [reward.id]: errorMessage(error, 'Redemption failed.'),
      }))
    } finally {
      setRedeemingId(null)
    }
  }

  return (
    <div>
      <h1>Rewards</h1>

      {balanceState.phase !== 'error' && (
        <p className="reward-balance">
          {balanceState.phase === 'loading' && 'Loading balance...'}
          {balanceState.phase === 'loaded' && `Your balance: ${balanceState.data} points`}
        </p>
      )}
      {balanceState.phase === 'error' && (
        <p className="reward-balance" role="alert">
          {balanceState.message} <button onClick={loadBalance}>Retry</button>
        </p>
      )}

      {currentRole === 'adult' && <Link to="/rewards/new">+ Create reward</Link>}

      {rewardsState.phase === 'loading' && <p>Loading rewards...</p>}
      {rewardsState.phase === 'error' && (
        <p role="alert">
          {rewardsState.message} <button onClick={loadRewards}>Retry</button>
        </p>
      )}
      {rewardsState.phase === 'loaded' && rewardsState.data.length === 0 && (
        <div>
          <p>No rewards yet.</p>
          {currentRole === 'adult' && <Link to="/rewards/new">Create your first reward</Link>}
        </div>
      )}
      {rewardsState.phase === 'loaded' && rewardsState.data.length > 0 && (
        // Rendered in the order the backend returns (name asc, id asc,
        // already deterministic) -- no client-side re-sort, per spec: an
        // API-defined ordering is respected rather than overridden.
        <ul className="reward-list">
          {rewardsState.data.map((reward) => {
            const knownBalance = balanceState.phase === 'loaded' ? balanceState.data : null
            const insufficientBalance = knownBalance !== null && knownBalance < reward.cost_points
            const isConfirming = confirmingId === reward.id
            const isRedeeming = redeemingId === reward.id

            return (
              <li key={reward.id} className="reward-card">
                <p className="reward-card-title">{reward.name}</p>
                {reward.description && <p>{reward.description}</p>}
                <p>Cost: {reward.cost_points} points</p>
                {insufficientBalance && <p>Not enough points</p>}

                {currentRole === 'adult' && <Link to={`/rewards/${reward.id}/edit`}>Edit</Link>}

                {!isConfirming && (
                  <button onClick={() => startRedeeming(reward.id)} disabled={insufficientBalance}>
                    Redeem
                  </button>
                )}

                {isConfirming && (
                  <div className="redeem-confirm">
                    <p>Redeem &quot;{reward.name}&quot;?</p>
                    <p>Cost: {reward.cost_points} points</p>
                    <p>
                      Your balance: {balanceState.phase === 'loaded' ? balanceState.data : '...'}{' '}
                      points
                    </p>
                    <button onClick={cancelRedeeming} disabled={isRedeeming}>
                      Cancel
                    </button>
                    <button onClick={() => confirmRedeem(reward)} disabled={isRedeeming}>
                      {isRedeeming ? 'Redeeming...' : 'Redeem'}
                    </button>
                  </div>
                )}

                {redemptionErrors[reward.id] && (
                  <p role="alert">{redemptionErrors[reward.id]}</p>
                )}
                {redemptionSuccess?.rewardId === reward.id && (
                  <p role="status">{redemptionSuccess.message}</p>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default RewardsPage
