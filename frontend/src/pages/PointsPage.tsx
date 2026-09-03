import { useCallback, useEffect, useState } from 'react'
import { getBalance, getHistory, type PointTransaction } from '../api/points'
import { getTaskExecutions, getTasks, type Task } from '../api/tasks'

type BalanceState =
  | { phase: 'loading' }
  | { phase: 'loaded'; balance: number }
  | { phase: 'error'; message: string }

type HistoryState =
  | { phase: 'loading' }
  | { phase: 'loaded'; transactions: PointTransaction[] }
  | { phase: 'error'; message: string }

const REASON_LABELS: Record<PointTransaction['reason'], string> = {
  TASK_COMPLETED: 'Task completed',
  REWARD_REDEEMED: 'Reward redeemed',
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

// A transaction only carries a task_execution_id; resolving it to a task
// title is a two-hop lookup (execution -> task_id -> task) since neither
// endpoint embeds the other (this codebase never uses ORM-style nested
// responses -- see the backend's explicit-join convention).
function useTaskTitleByExecutionId() {
  const [titleByExecutionId, setTitleByExecutionId] = useState<Record<string, string>>({})

  useEffect(() => {
    Promise.all([getTasks(), getTaskExecutions()])
      .then(([tasks, executions]) => {
        const tasksById: Record<string, Task> = Object.fromEntries(
          tasks.map((task) => [task.id, task]),
        )
        const titles = Object.fromEntries(
          executions
            .map((execution): [string, string | undefined] => [
              execution.id,
              tasksById[execution.task_id]?.title,
            ])
            .filter((entry): entry is [string, string] => entry[1] !== undefined),
        )
        setTitleByExecutionId(titles)
      })
      .catch(() => {
        // A task title is a presentation nicety on top of the transaction
        // reason; if this fails, history still renders without it. There is
        // no existing endpoint to resolve a redemption_id back to a reward
        // name, so redemption transactions never get this extra line.
      })
  }, [])

  return titleByExecutionId
}

function PointsPage() {
  const [balanceState, setBalanceState] = useState<BalanceState>({ phase: 'loading' })
  const [historyState, setHistoryState] = useState<HistoryState>({ phase: 'loading' })
  const taskTitleByExecutionId = useTaskTitleByExecutionId()

  const loadBalance = useCallback(() => {
    setBalanceState({ phase: 'loading' })
    getBalance()
      .then((balance) => setBalanceState({ phase: 'loaded', balance: balance.balance }))
      .catch((error: unknown) =>
        setBalanceState({ phase: 'error', message: errorMessage(error, 'Could not load balance.') }),
      )
  }, [])

  const loadHistory = useCallback(() => {
    setHistoryState({ phase: 'loading' })
    getHistory()
      .then((transactions) => setHistoryState({ phase: 'loaded', transactions }))
      .catch((error: unknown) =>
        setHistoryState({
          phase: 'error',
          message: errorMessage(error, 'Could not load points history.'),
        }),
      )
  }, [])

  useEffect(() => {
    loadBalance()
  }, [loadBalance])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  return (
    <div>
      <h1>Points</h1>

      <section aria-labelledby="balance-heading">
        <h2 id="balance-heading">Current balance</h2>
        {balanceState.phase === 'loading' && <p>Loading balance...</p>}
        {balanceState.phase === 'error' && (
          <p role="alert">
            {balanceState.message} <button onClick={loadBalance}>Retry</button>
          </p>
        )}
        {balanceState.phase === 'loaded' && <p>{balanceState.balance} points</p>}
      </section>

      <section aria-labelledby="history-heading">
        <h2 id="history-heading">History</h2>
        {historyState.phase === 'loading' && <p>Loading history...</p>}
        {historyState.phase === 'error' && (
          <p role="alert">
            {historyState.message} <button onClick={loadHistory}>Retry</button>
          </p>
        )}
        {historyState.phase === 'loaded' && historyState.transactions.length === 0 && (
          <p>No points history yet.</p>
        )}
        {historyState.phase === 'loaded' && historyState.transactions.length > 0 && (
          // The backend already orders history by created_at desc, id desc
          // -- rendered as returned, no client-side re-sort.
          <ul className="transaction-list">
            {historyState.transactions.map((txn) => {
              const taskTitle = txn.task_execution_id
                ? taskTitleByExecutionId[txn.task_execution_id]
                : undefined
              return (
                <li key={txn.id} className="transaction-card">
                  <p className="transaction-amount">
                    {txn.amount > 0 ? '+' : ''}
                    {txn.amount} points
                  </p>
                  <p>{REASON_LABELS[txn.reason]}</p>
                  {taskTitle && <p>&quot;{taskTitle}&quot;</p>}
                  <p>{new Date(txn.created_at).toLocaleDateString()}</p>
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </div>
  )
}

export default PointsPage
