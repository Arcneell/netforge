import axios, { type AxiosError, type AxiosInstance, type AxiosRequestConfig } from 'axios'
import type { ApiErrorBody } from '@/api/types'

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

// Getter for the user's current UI locale — used by the request interceptor
// to tag every call with `Accept-Language`. Wired from main.ts after i18n is
// created so this module stays free of i18n imports (avoids a circular
// dependency between api/client → i18n → some store that uses request()).
let getLocale: () => string | null = () => null

export function registerLocaleProvider(fn: () => string | null): void {
  getLocale = fn
}

/** Read the current UI locale. Used by callers that bypass the axios
 *  request interceptor (e.g. the raw `fetch` SSE call needs to attach
 *  `Accept-Language` itself). */
export function getActiveLocale(): string | null {
  return getLocale()
}

export const api: AxiosInstance = axios.create({
  baseURL: '/api',
  withCredentials: true, // send the netforge_session cookie
  timeout: 20000,
  headers: {
    Accept: 'application/json',
  },
})

// Tag every outgoing request with the user's current UI locale so the backend
// can localise responses where it matters — today the AI features pick this
// up to answer in the same language the user is reading.
api.interceptors.request.use((config) => {
  const locale = getLocale()
  if (locale) {
    config.headers.set('Accept-Language', locale)
  }
  return config
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
    // Three envelope shapes in production:
    //   1. Canonical:        `{detail: {error: {code, message, details?}}}`
    //      FastAPI wraps HTTPException.detail in `detail`, and our
    //      `http_error` helper builds `{error: {code, message}}` as
    //      the inner detail. Two levels deep.
    //   2. Bare:             `{detail: "<exception type>: <message>"}`
    //      Raw HTTPException calls that didn't use our helper — the AI
    //      502 / 422 / 501 catch-alls historically take this path.
    //   3. Top-level error:  `{error: {code, message, details?}}`
    //      Reserved for cases where a router returns a JSONResponse
    //      directly (e.g. rate-limit middleware) instead of raising.
    // Pick the canonical structure first; fall back to bare string;
    // legacy top-level last. Pre-fix, the interceptor only read shape #3
    // — every real backend error fell through to axios's generic
    // "Request failed with status code XXX".
    const innerError =
      (data && typeof data.detail === 'object' && data.detail !== null
        ? (data.detail as { error?: ApiErrorBody['error'] }).error
        : undefined) ?? data?.error
    const detailString = typeof data?.detail === 'string' ? data.detail : undefined
    const code = innerError?.code ?? (detailString ? 'UPSTREAM_ERROR' : 'UNKNOWN')
    const message = innerError?.message ?? detailString ?? error.message ?? 'Unknown error'

    if (status === 401) hooks.onUnauthorized?.()
    if (status === 403) hooks.onForbidden?.()

    return Promise.reject(new ApiError(status, code, message, innerError?.details))
  },
)

export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const res = await api.request<T>(config)
  return res.data
}
