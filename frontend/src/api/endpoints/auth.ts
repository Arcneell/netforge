import { request } from '@/api/client'

export type UserRole = 'admin' | 'viewer'

export interface CurrentUser {
  id: number
  email: string | null
  display_name: string | null
  role: UserRole
  provider: string
}

/**
 * `full` inherits the owner's role verbatim (the historical, still-default
 * behaviour). `read_only` caps the token to viewer-level reads for its
 * whole lifetime, even if the owner is an admin — see backend
 * `app/auth/dependencies.py::get_current_user`.
 */
export type ApiTokenScope = 'full' | 'read_only'

// TODO(gen:types): once the backend is reachable, run `npm run gen:types`
// to regenerate `src/api/schema.d.ts` (it still predates the `scope` field
// added to ApiTokenCreate/ApiTokenRead) and fold any renamed fields back in
// here by hand, same as every other hand-curated alias in this file.
export interface ApiToken {
  id: number
  user_id: number
  name: string
  prefix: string
  scope: ApiTokenScope
  created_at: string
  expires_at: string | null
  last_used_at: string | null
  revoked_at: string | null
}

export interface ApiTokenCreate {
  name: string
  expires_at?: string | null
  /** Defaults server-side to `full` when omitted. */
  scope?: ApiTokenScope
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
