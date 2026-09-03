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

export class RewardNotFoundError extends Error {
  constructor() {
    super('Reward not found')
  }
}

export function getRewards(): Promise<Reward[]> {
  return request<Reward[]>('/api/rewards')
}

export function getReward(id: string): Promise<Reward> {
  // The backend has no GET /api/rewards/{id} -- only the list endpoint
  // (Rewards are a small global catalog). Reusing the list rather than
  // adding a new backend endpoint keeps this within the existing API
  // surface; the Edit page needs this to work on direct navigation, so it
  // always fetches fresh rather than relying on the list page's in-memory
  // state.
  return getRewards().then((rewards) => {
    const reward = rewards.find((candidate) => candidate.id === id)
    if (!reward) {
      throw new RewardNotFoundError()
    }
    return reward
  })
}

export function createReward(input: RewardInput): Promise<Reward> {
  return request<Reward>('/api/rewards', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updateReward(id: string, input: RewardInput): Promise<Reward> {
  return request<Reward>(`/api/rewards/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}
