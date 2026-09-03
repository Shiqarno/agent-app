import { request } from './http'

export type UserRole = 'adult' | 'child'

export type UserSummary = {
  id: string
  name: string
  role: UserRole
}

export type CreatedUser = {
  id: string
  name: string
  role: UserRole
  created_at: string
  updated_at: string
  // Returned once, at creation time, so the creating Adult can hand it to
  // the new User. Never persisted raw server-side and never returned by any
  // other endpoint (Issue #11).
  activation_token: string
}

export type UserInput = {
  name: string
  role: UserRole
}

export function getUsers(): Promise<UserSummary[]> {
  return request<UserSummary[]>('/api/users')
}

export function createUser(input: UserInput): Promise<CreatedUser> {
  return request<CreatedUser>('/api/users', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}
