import { request } from './http'

export type Project = {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export type ProjectInput = {
  name: string
  description: string | null
}

export function getProjects(): Promise<Project[]> {
  return request<Project[]>('/api/projects')
}

export function createProject(input: ProjectInput): Promise<Project> {
  return request<Project>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updateProject(id: string, input: ProjectInput): Promise<Project> {
  return request<Project>(`/api/projects/${id}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}

export function deleteProject(id: string): Promise<void> {
  return request<void>(`/api/projects/${id}`, {
    method: 'DELETE',
  })
}
