import { ApiError, request } from './http'

export { ApiError }

export type TaskStatus =
  | 'ASSIGNED'
  | 'IN_PROGRESS'
  | 'AWAITING_CONFIRMATION'
  | 'COMPLETED'
  | 'CANCELLED'

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

export type TaskUpdateInput = {
  title?: string
  description?: string
}

export function getTasks(): Promise<Task[]> {
  return request<Task[]>('/api/tasks')
}

export function getTask(id: string): Promise<Task> {
  return request<Task>(`/api/tasks/${id}`)
}

export function createTask(input: TaskInput): Promise<Task> {
  return request<Task>('/api/tasks', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updateTask(id: string, input: TaskUpdateInput): Promise<Task> {
  return request<Task>(`/api/tasks/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  })
}

export function reassignTask(id: string, assignedTo: string): Promise<Task> {
  return request<Task>(`/api/tasks/${id}/reassign`, {
    method: 'POST',
    body: JSON.stringify({ assigned_to: assignedTo }),
  })
}

export function startTask(id: string): Promise<Task> {
  return request<Task>(`/api/tasks/${id}/start`, { method: 'POST' })
}

export function readyTask(id: string): Promise<Task> {
  return request<Task>(`/api/tasks/${id}/ready`, { method: 'POST' })
}

export function confirmTask(id: string): Promise<Task> {
  return request<Task>(`/api/tasks/${id}/confirm`, { method: 'POST' })
}

export function cancelTask(id: string): Promise<Task> {
  return request<Task>(`/api/tasks/${id}/cancel`, { method: 'POST' })
}
