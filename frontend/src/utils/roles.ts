import type { UserRole } from '@/api'

/**
 * Single source of truth for the role hierarchy: `admin` satisfies every
 * requirement, `viewer` only satisfies `viewer`.
 *
 * Shared by the router guard (`meta.minRole`) and the `useAuth().hasRole`
 * composable — the two used to carry identical private copies, which is
 * exactly the kind of duplication that drifts the day a third role lands.
 */
export function roleSatisfies(actual: UserRole | null | undefined, required: UserRole): boolean {
  if (!actual) return false
  if (required === 'viewer') return actual === 'viewer' || actual === 'admin'
  return actual === required
}
