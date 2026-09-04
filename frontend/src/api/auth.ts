import { request } from './http'

export type CurrentUser = {
  id: string
  name: string
  role: 'adult' | 'child'
  avatar_id: string
}

export function login(email: string, password: string): Promise<CurrentUser> {
  return request<CurrentUser>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function activate(token: string, email: string, password: string): Promise<CurrentUser> {
  return request<CurrentUser>('/api/auth/activate', {
    method: 'POST',
    body: JSON.stringify({ token, email, password }),
  })
}

export function logout(): Promise<void> {
  return request<void>('/api/auth/logout', { method: 'POST' })
}

export function me(): Promise<CurrentUser> {
  return request<CurrentUser>('/api/auth/me')
}
