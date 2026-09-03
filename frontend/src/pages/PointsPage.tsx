import { useEffect, useState } from 'react'
import { getBalance, getHistory, type PointTransaction } from '../api/points'

type BalanceState =
  | { phase: 'loading' }
  | { phase: 'loaded'; balance: number }
  | { phase: 'error'; message: string }

type HistoryState =
  | { phase: 'loading' }
  | { phase: 'loaded'; transactions: PointTransaction[] }
  | { phase: 'error'; message: string }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function PointsPage() {
  const [balanceState, setBalanceState] = useState<BalanceState>({ phase: 'loading' })
  const [historyState, setHistoryState] = useState<HistoryState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false
    getBalance()
      .then((balance) => {
        if (!cancelled) setBalanceState({ phase: 'loaded', balance: balance.balance })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setBalanceState({ phase: 'error', message: errorMessage(error, 'Unable to load balance.') })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    getHistory()
      .then((transactions) => {
        if (!cancelled) setHistoryState({ phase: 'loaded', transactions })
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setHistoryState({
            phase: 'error',
            message: errorMessage(error, 'Unable to load history.'),
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div>
      <h1>Points</h1>
      {balanceState.phase === 'loading' && <p>Loading...</p>}
      {balanceState.phase === 'error' && <p role="alert">{balanceState.message}</p>}
      {balanceState.phase === 'loaded' && <p>Balance: {balanceState.balance}</p>}

      <h2>History</h2>
      {historyState.phase === 'loading' && <p>Loading...</p>}
      {historyState.phase === 'error' && <p role="alert">{historyState.message}</p>}
      {historyState.phase === 'loaded' && historyState.transactions.length === 0 && (
        <p>No point transactions yet.</p>
      )}
      {historyState.phase === 'loaded' && historyState.transactions.length > 0 && (
        <ul>
          {historyState.transactions.map((txn) => (
            <li key={txn.id}>
              {txn.amount > 0 ? '+' : ''}
              {txn.amount} — {txn.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default PointsPage
