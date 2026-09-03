import { request } from './http'

export type Balance = {
  balance: number
}

export type PointTransaction = {
  id: string
  amount: number
  reason: 'TASK_COMPLETED' | 'REWARD_REDEEMED'
  task_id: string | null
  redemption_id: string | null
  created_at: string
}

export function getBalance(): Promise<Balance> {
  return request<Balance>('/api/points/balance')
}

export function getHistory(): Promise<PointTransaction[]> {
  return request<PointTransaction[]>('/api/points/history')
}
