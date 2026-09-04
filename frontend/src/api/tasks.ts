import { ApiError, request } from './http'

export { ApiError }

export type TaskExecutionStatus =
  | 'ASSIGNED'
  | 'IN_PROGRESS'
  | 'AWAITING_CONFIRMATION'
  | 'COMPLETED'
  | 'CANCELLED'

export type Task = {
  id: string
  title: string
  description: string | null
  reward_points: number
  is_active: boolean
  created_by: string
  created_at: string
  updated_at: string
}

export type TaskExecution = {
  id: string
  task_id: string
  user_id: string
  status: TaskExecutionStatus
  reward_points: number
  created_at: string
  updated_at: string
}

export type TaskInput = {
  title: string
  description: string | null
  assigned_to?: string
  reward_points: number
}

export type TaskUpdateInput = {
  title?: string
  description?: string
  reward_points?: number
  is_active?: boolean
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

export function claimTask(id: string): Promise<TaskExecution> {
  return request<TaskExecution>(`/api/tasks/${id}/claim`, { method: 'POST' })
}

export function activateTask(id: string): Promise<Task> {
  return request<Task>(`/api/tasks/${id}/activate`, { method: 'POST' })
}

export function getTaskExecutions(): Promise<TaskExecution[]> {
  return request<TaskExecution[]>('/api/task-executions')
}

export function getTaskExecution(id: string): Promise<TaskExecution> {
  return request<TaskExecution>(`/api/task-executions/${id}`)
}

export function reassignTaskExecution(id: string, assignedTo: string): Promise<TaskExecution> {
  return request<TaskExecution>(`/api/task-executions/${id}/reassign`, {
    method: 'POST',
    body: JSON.stringify({ assigned_to: assignedTo }),
  })
}

export function startTaskExecution(id: string): Promise<TaskExecution> {
  return request<TaskExecution>(`/api/task-executions/${id}/start`, { method: 'POST' })
}

export function readyTaskExecution(id: string): Promise<TaskExecution> {
  return request<TaskExecution>(`/api/task-executions/${id}/ready`, { method: 'POST' })
}

export function confirmTaskExecution(id: string): Promise<TaskExecution> {
  return request<TaskExecution>(`/api/task-executions/${id}/confirm`, { method: 'POST' })
}

export function cancelTaskExecution(id: string): Promise<TaskExecution> {
  return request<TaskExecution>(`/api/task-executions/${id}/cancel`, { method: 'POST' })
}
