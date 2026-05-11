import { request } from '@/api/client'

export type UserRole = 'admin' | 'viewer'

export interface CurrentUser {
  id: number
  email: string | null
  display_name: string | null
  role: UserRole
  provider: string
}

export const authApi = {
  /** Returns the currently authenticated user, or throws 401 if no session. */
  me(): Promise<CurrentUser> {
    return request<CurrentUser>({ method: 'GET', url: '/auth/me' })
  },

  logout(): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>({ method: 'POST', url: '/auth/logout' })
  },

  /**
   * URL of the backend route that starts the OAuth/OIDC redirect dance.
   * Must be visited via a top-level navigation (window.location.href) — fetch/XHR
   * would lose the cookies on the IdP round-trip.
   */
  loginUrl(): string {
    return '/api/auth/login'
  },
}
