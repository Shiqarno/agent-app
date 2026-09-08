import type { CurrentUser } from './auth'
import { ApiError, request } from './http'

export { ApiError }

export type UserRole = 'adult' | 'child'

export type ActivationStatus = 'ACTIVE' | 'PENDING'

export type UserSummary = {
  id: string
  name: string
  role: UserRole
  avatar_id: string
  activation_status: ActivationStatus
  // Whether a TelegramIdentity exists for this User (Issue #33) --
  // independent of activation_status, which reflects Web credential (PIN)
  // setup only.
  telegram_connected: boolean
}

export type CreatedUser = {
  id: string
  name: string
  role: UserRole
  avatar_id: string
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

export function updateMyAvatar(avatarId: string): Promise<CurrentUser> {
  return request<CurrentUser>('/api/users/me', {
    method: 'PATCH',
    body: JSON.stringify({ avatar_id: avatarId }),
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

// The Telegram bot's public @username -- not a secret (unlike
// TELEGRAM_BOT_TOKEN, which is never sent to the browser), configured via
// the same VITE_* build-time mechanism as VITE_API_URL (Issue #33).
const TELEGRAM_BOT_USERNAME = import.meta.env.VITE_TELEGRAM_BOT_USERNAME ?? ''

// Same activation token as activationUrlFor above (this endpoint's raw
// token is valid for either channel -- see routers.users.
// regenerate_user_activation), presented as a Telegram deep link instead
// of a Web link.
export function activationTelegramUrlFor(token: string): string {
  return `https://t.me/${TELEGRAM_BOT_USERNAME}?start=${encodeURIComponent(token)}`
}
