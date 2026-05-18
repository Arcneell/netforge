import { ref, watch, type Ref } from 'vue'

/**
 * A `ref` whose value is persisted to `localStorage` under the given key.
 *
 * Use this for tiny per-device UI state — view-mode toggles, last selected
 * tab, expand / collapse state, etc. — where we want the user's choice to
 * survive a page reload but DON'T want it synced server-side (that would
 * mean an API call, an audit log entry, and a cross-device surprise).
 *
 * Storage is JSON-encoded so non-string values round-trip safely. If parsing
 * fails (corrupted entry, version mismatch) we fall back to `defaultValue`
 * rather than throwing — UI state is never worth crashing the view over.
 */
export function useStoredRef<T>(key: string, defaultValue: T): Ref<T> {
  const initial = (() => {
    try {
      const raw = localStorage.getItem(key)
      if (raw === null) return defaultValue
      return JSON.parse(raw) as T
    } catch {
      // Browser refused (private mode, quota) or the stored payload is no
      // longer valid JSON — either way fall back, don't crash.
      return defaultValue
    }
  })()

  const r = ref(initial) as Ref<T>

  watch(
    r,
    (v) => {
      try {
        localStorage.setItem(key, JSON.stringify(v))
      } catch {
        // Quota / private mode again — silently drop the write. The runtime
        // state is still correct, the next reload just falls back to default.
      }
    },
    { deep: true },
  )

  return r
}
