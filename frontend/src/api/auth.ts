import { ApiError, request } from './http'

export { ApiError }

export type CurrentUser = {
  id: string
  name: string
  role: 'adult' | 'child'
  avatar_id: string
  pin_configured: boolean
}

export type Profile = {
  id: string
  name: string
  avatar_id: string
}

export function login(email: string, password: string): Promise<CurrentUser> {
  return request<CurrentUser>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function activate(
  token: string,
  email: string,
  pin: string,
  password?: string,
): Promise<CurrentUser> {
  const body: Record<string, string> = { token, email, pin }
  if (password) {
    body.password = password
  }
  return request<CurrentUser>('/api/auth/activate', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function logout(): Promise<void> {
  return request<void>('/api/auth/logout', { method: 'POST' })
}

export function me(): Promise<CurrentUser> {
  return request<CurrentUser>('/api/auth/me')
}

export function getProfiles(): Promise<Profile[]> {
  return request<Profile[]>('/api/auth/profiles')
}

export function pinLogin(userId: string, pin: string): Promise<CurrentUser> {
  return request<CurrentUser>('/api/auth/pin-login', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, pin }),
  })
}

export function setupPin(pin: string): Promise<CurrentUser> {
  return request<CurrentUser>('/api/auth/pin', {
    method: 'PATCH',
    body: JSON.stringify({ pin }),
  })
}
