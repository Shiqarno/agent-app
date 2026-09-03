import { request } from './http'

export type TaskStatus = 'ASSIGNED' | 'IN_PROGRESS' | 'AWAITING_CONFIRMATION' | 'COMPLETED'

export type Task = {
  id: string
  title: string
  description: string | null
  assigned_to: string
  created_by: string
  reward_points: number
  status: TaskStatus
  created_at: string
  updated_at: string
}

export type TaskInput = {
  title: string
  description: string | null
  assigned_to: string
  reward_points: number
}

export function getTasks(): Promise<Task[]> {
  return request<Task[]>('/api/tasks')
}

export function createTask(input: TaskInput): Promise<Task> {
  return request<Task>('/api/tasks', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function confirmTask(id: string): Promise<Task> {
  return request<Task>(`/api/tasks/${id}/confirm`, { method: 'POST' })
}
