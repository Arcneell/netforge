import { storeToRefs } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import type { UserRole } from '@/api'
import { roleSatisfies } from '@/utils/roles'

/**
 * Composable façade over the auth Pinia store.
 *
 * View-layer code should prefer this over importing the store directly:
 * keeps refs reactive (`storeToRefs`) and surfaces a tighter, more stable
 * API than the raw store internals.
 */
export function useAuth() {
  const store = useAuthStore()
  const { user, status, isAuthenticated, role, isAdmin } = storeToRefs(store)

  function hasRole(required: UserRole): boolean {
    return roleSatisfies(role.value, required)
  }

  return {
    user,
    status,
    isAuthenticated,
    role,
    isAdmin,
    hasRole,
    fetchMe: store.fetchMe,
    startLogin: store.startLogin,
    consumePostLoginPath: store.consumePostLoginPath,
    logout: store.logout,
  }
}
