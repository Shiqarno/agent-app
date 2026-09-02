import { request } from './http'

export type CurrentUser = {
  id: string
  name: string
  role: 'adult' | 'child'
}

export function login(email: string, password: string): Promise<CurrentUser> {
  return request<CurrentUser>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function logout(): Promise<void> {
  return request<void>('/api/auth/logout', { method: 'POST' })
}

export function me(): Promise<CurrentUser> {
  return request<CurrentUser>('/api/auth/me')
}
