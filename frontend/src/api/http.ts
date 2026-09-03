const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

const CSRF_COOKIE_NAME = 'csrf_token'
const CSRF_HEADER_NAME = 'X-CSRF-Token'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

type ApiErrorBody = {
  error?: {
    code?: string
    message?: string
  }
}

// Extends Error (not a parallel error type) so every existing `error
// instanceof Error && error.message` check across the app keeps working
// unchanged. `code` is additive, for the rare caller that needs to branch on
// the backend's error code rather than just display the message.
export class ApiError extends Error {
  code: string | null

  constructor(message: string, code: string | null) {
    super(message)
    this.code = code
  }
}

async function extractError(response: Response): Promise<{ message: string; code: string | null }> {
  try {
    const body = (await response.json()) as ApiErrorBody
    if (typeof body?.error?.message === 'string' && body.error.message) {
      return {
        message: body.error.message,
        code: typeof body.error.code === 'string' ? body.error.code : null,
      }
    }
  } catch {
    // response body was not JSON, or did not match the expected error shape
  }
  return { message: `Request failed with status ${response.status}`, code: null }
}

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

// Shared fetch wrapper for all API calls. Always sends the session cookie
// (`credentials: 'include'`) so the backend's cookie-based auth (Issue #9)
// works when frontend and backend are on different origins in development,
// and attaches the CSRF header the backend's double-submit-cookie check
// requires on state-changing requests (GET/HEAD/OPTIONS are exempt, matching
// the backend).
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  }

  if (!SAFE_METHODS.has(method)) {
    const csrfToken = readCookie(CSRF_COOKIE_NAME)
    if (csrfToken) {
      headers[CSRF_HEADER_NAME] = csrfToken
    }
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: 'include',
    headers,
  })

  if (!response.ok) {
    const { message, code } = await extractError(response)
    throw new ApiError(message, code)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}
