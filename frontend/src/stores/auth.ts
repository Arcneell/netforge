import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ApiError, authApi, type CurrentUser, type UserRole } from '@/api'

type Status = 'idle' | 'loading' | 'authenticated' | 'anonymous'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<CurrentUser | null>(null)
  const status = ref<Status>('idle')
  const error = ref<string | null>(null)

  const isAuthenticated = computed(() => status.value === 'authenticated' && user.value !== null)
  const role = computed<UserRole | null>(() => user.value?.role ?? null)
  const isAdmin = computed(() => role.value === 'admin')

  /** Pulls the current user from /api/auth/me. Tolerates 401 (sets anonymous). */
  async function fetchMe(): Promise<void> {
    status.value = 'loading'
    error.value = null
    try {
      user.value = await authApi.me()
      status.value = 'authenticated'
    } catch (err) {
      user.value = null
      if (err instanceof ApiError && err.status === 401) {
        status.value = 'anonymous'
      } else {
        status.value = 'anonymous'
        error.value = err instanceof Error ? err.message : 'unknown'
      }
    }
  }

  function startLogin(nextPath?: string): void {
    // Persist the post-login destination so the SPA can restore it after the callback
    // (the backend just sends the user to "/" — see backend/app/routers/auth.py).
    if (nextPath) {
      try {
        sessionStorage.setItem('netforge.postLoginPath', nextPath)
      } catch {
        // ignore
      }
    }
    window.location.href = authApi.loginUrl()
  }

  function consumePostLoginPath(): string | null {
    try {
      const v = sessionStorage.getItem('netforge.postLoginPath')
      if (v) sessionStorage.removeItem('netforge.postLoginPath')
      return _sanitisePostLoginPath(v)
    } catch {
      return null
    }
  }

  /**
   * Defence against an open-redirect via `?next=` on /login. We persist
   * the unvalidated value (so the LoginView UX stays simple), but only
   * accept it back as a target if it looks like an internal path:
   *
   *   - starts with a single `/`
   *   - does NOT start with `//` (protocol-relative URL like //evil.com)
   *   - does NOT contain a scheme (`https:`, `javascript:`, ...)
   *   - does NOT contain control chars / newlines / backslashes
   *
   * Anything that fails is dropped, so the caller falls through to "/".
   */
  function _sanitisePostLoginPath(raw: string | null): string | null {
    if (!raw) return null
    if (raw.length > 2000) return null
    // Must start with `/` and not `//` (protocol-relative form).
    if (!raw.startsWith('/') || raw.startsWith('//')) return null
    // Block backslash-paths and any non-printable / newline char that
    // can cause CRLF injection or split the URL parser.
    if (/[\\\x00-\x1f]/.test(raw)) return null
    // Block embedded scheme (a single colon before the first `/?#`).
    // `/foo?bar=baz:qux` is fine because the colon is past the `?`.
    const stop = raw.search(/[?#]/)
    const pathPart = stop < 0 ? raw : raw.slice(0, stop)
    if (pathPart.includes(':')) return null
    return raw
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } catch {
      // best-effort; even on failure we clear local state
    }
    user.value = null
    status.value = 'anonymous'
  }

  function setAnonymous(): void {
    user.value = null
    status.value = 'anonymous'
  }

  return {
    user,
    status,
    error,
    isAuthenticated,
    role,
    isAdmin,
    fetchMe,
    startLogin,
    consumePostLoginPath,
    logout,
    setAnonymous,
  }
})
