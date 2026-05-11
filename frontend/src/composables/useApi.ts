import { api, ApiError, request } from '@/api'
import { useToast } from '@/composables/useToast'

/**
 * Thin wrapper around the shared axios instance.
 *
 * - Returns the bare typed payload (no AxiosResponse envelope).
 * - Auto-toasts non-401 errors; 401s are owned by the auth store, which
 *   redirects to /login via the global hook wired in main.ts.
 */
export function useApi() {
  const { error: toastError } = useToast()

  async function wrap<T>(fn: () => Promise<T>, options: { silent?: boolean } = {}): Promise<T> {
    try {
      return await fn()
    } catch (err) {
      if (!options.silent && err instanceof ApiError && err.status !== 401) {
        toastError(err.message)
      }
      throw err
    }
  }

  return {
    raw: api,
    request,
    get: <T>(url: string, params?: Record<string, unknown>, options?: { silent?: boolean }) =>
      wrap<T>(() => request<T>({ method: 'GET', url, params }), options),
    post: <T>(url: string, data?: unknown, options?: { silent?: boolean }) =>
      wrap<T>(() => request<T>({ method: 'POST', url, data }), options),
    put: <T>(url: string, data?: unknown, options?: { silent?: boolean }) =>
      wrap<T>(() => request<T>({ method: 'PUT', url, data }), options),
    patch: <T>(url: string, data?: unknown, options?: { silent?: boolean }) =>
      wrap<T>(() => request<T>({ method: 'PATCH', url, data }), options),
    delete: <T>(url: string, options?: { silent?: boolean }) =>
      wrap<T>(() => request<T>({ method: 'DELETE', url }), options),
  }
}
