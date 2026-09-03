import { request } from './http'

export type Reward = {
  id: string
  name: string
  description: string | null
  cost_points: number
  created_by: string
  created_at: string
  updated_at: string
}

export type RewardInput = {
  name: string
  description: string | null
  cost_points: number
}

export function getRewards(): Promise<Reward[]> {
  return request<Reward[]>('/api/rewards')
}

export function createReward(input: RewardInput): Promise<Reward> {
  return request<Reward>('/api/rewards', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
