import { request } from '@/api/client'

export type UserRole = 'admin' | 'viewer'

export interface CurrentUser {
  id: number
  email: string | null
  display_name: string | null
  role: UserRole
  provider: string
}

export interface ApiToken {
  id: number
  user_id: number
  name: string
  prefix: string
  created_at: string
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
}

export interface ApiTokenCreate {
  name: string
  expires_at?: string | null
}

/** Returned by POST /api/auth/tokens. `token` is the plaintext, surfaced
 *  exactly once — display it and let the user copy, never persist it. */
export interface ApiTokenCreated extends ApiToken {
  token: string
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

  // --- API tokens --------------------------------------------------------

  listTokens(): Promise<ApiToken[]> {
    return request<ApiToken[]>({ method: 'GET', url: '/auth/tokens' })
  },
  createToken(data: ApiTokenCreate): Promise<ApiTokenCreated> {
    return request<ApiTokenCreated>({ method: 'POST', url: '/auth/tokens', data })
  },
  revokeToken(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/auth/tokens/${id}` })
  },
}
