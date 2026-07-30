import { nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

/**
 * Deep-link landing effect for list pages reached via `?highlight=<id>`
 * (GlobalSearch uses this for entities — VLANs, sites, rooms — that have no
 * dedicated detail route and only ever land on a list).
 *
 * Call `applyHighlight()` once the list's rows are in the DOM (end of the
 * page's `load()`); pass `rowClass` straight through to `DataTable`'s
 * `row-class` prop. Rows must expose `data-row-id="<id>"`, which
 * `DataTable` already sets on every `<tr>` / `<li>`.
 *
 * One-shot: after scrolling to and ringing the row, the `highlight` query
 * param is stripped so a reload or back-navigation doesn't replay it.
 */
export function useRowHighlight() {
  const route = useRoute()
  const router = useRouter()
  const highlightedId = ref<string | null>(null)

  async function applyHighlight() {
    const raw = route.query.highlight
    const id = typeof raw === 'string' ? raw : null
    if (!id) return

    await nextTick()
    const el = document.querySelector<HTMLElement>(`[data-row-id="${CSS.escape(id)}"]`)
    if (el) {
      el.scrollIntoView({ block: 'center', behavior: 'smooth' })
      highlightedId.value = id
      setTimeout(() => {
        if (highlightedId.value === id) highlightedId.value = null
      }, 2200)
    }

    // Strip the param regardless of whether the row was found (it may be on
    // a page/tab we haven't loaded) — it's a one-time landing cue, not
    // state worth keeping in the URL.
    const { highlight: _dropped, ...rest } = route.query
    router.replace({ query: rest })
  }

  function rowClass(row: { id: number | string }): string {
    return String(row.id) === highlightedId.value
      ? 'ring-2 ring-inset ring-primary-500 dark:ring-primary-400'
      : ''
  }

  // A search result clicked while ALREADY on the target list only changes
  // the query string — the component never remounts, so the page's
  // `onMounted` → `applyHighlight()` chain doesn't rerun. Re-apply whenever
  // a fresh `highlight` value shows up. (The strip-the-param replace above
  // retriggers this watcher with `undefined`, which `applyHighlight`
  // ignores, so there's no loop.)
  watch(
    () => route.query.highlight,
    (value) => {
      if (typeof value === 'string' && value) void applyHighlight()
    },
  )

  return { applyHighlight, rowClass }
}
