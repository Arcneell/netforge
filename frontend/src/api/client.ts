import axios, { type AxiosError, type AxiosInstance, type AxiosRequestConfig } from 'axios'

// Shape of every error response from the backend (see backend/app/services/errors.py).
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
  }
}

export class ApiError extends Error {
  status: number
  code: string
  details?: Record<string, unknown>

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

// Hooks consumed by the auth store / toast system. Wired in main.ts after Pinia
// is installed; kept as plain callbacks so this module stays framework-free.
export interface ApiHooks {
  onUnauthorized?: () => void
  onForbidden?: () => void
  onNetworkError?: (err: AxiosError) => void
}

const hooks: ApiHooks = {}

export function registerApiHooks(h: ApiHooks): void {
  Object.assign(hooks, h)
}

export const api: AxiosInstance = axios.create({
  baseURL: '/api',
  withCredentials: true, // send the netforge_session cookie
  timeout: 20000,
  headers: {
    Accept: 'application/json',
  },
})

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorBody>) => {
    if (!error.response) {
      // network failure, CORS, DNS, timeout — no HTTP layer
      hooks.onNetworkError?.(error)
      return Promise.reject(new ApiError(0, 'NETWORK_ERROR', error.message || 'Network error'))
    }

    const { status, data } = error.response
    const body = data?.error
    const code = body?.code ?? 'UNKNOWN'
    const message = body?.message ?? error.message ?? 'Unknown error'

    if (status === 401) hooks.onUnauthorized?.()
    if (status === 403) hooks.onForbidden?.()

    return Promise.reject(new ApiError(status, code, message, body?.details))
  },
)

export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const res = await api.request<T>(config)
  return res.data
}
