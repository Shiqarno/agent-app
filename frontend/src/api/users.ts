import { ApiError, request } from './http'

export { ApiError }

export type UserRole = 'adult' | 'child'

export type ActivationStatus = 'ACTIVE' | 'PENDING'

export type UserSummary = {
  id: string
  name: string
  role: UserRole
  activation_status: ActivationStatus
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

export type ActivationRegenerateResponse = {
  activation_token: string
  expires_at: string
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

export function regenerateActivation(userId: string): Promise<ActivationRegenerateResponse> {
  return request<ActivationRegenerateResponse>(`/api/users/${userId}/activation`, {
    method: 'POST',
  })
}

// The backend returns the raw token only, never a frontend-specific URL
// (Issue #11 §14, reaffirmed by Issue #16); the link is constructed here
// from the current origin so both the Add User and the Users-page "generate
// link" flows build it identically.
export function activationUrlFor(token: string): string {
  return `${window.location.origin}/activate?activation_token=${encodeURIComponent(token)}`
}
