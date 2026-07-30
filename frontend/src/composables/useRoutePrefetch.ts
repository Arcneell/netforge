/**
 * Route chunk prefetching.
 *
 * The problem this solves
 * ----------------------
 * Every route in `router/index.ts` is `component: () => import('...')`, which is
 * the right call for bundle size — `TopologyView` alone pulls cytoscape and
 * builds to ~590 kB. The cost is that **Vue Router does not change the route
 * until that dynamic import resolves.** So between the click and anything
 * appearing on screen, the old page sits there fully rendered and completely
 * inert. No spinner, no fade, nothing: the router simply has not navigated yet.
 *
 * Measured on the dev server, serving just a view's top-level module cost
 * ~0.7-0.9s cold versus ~0.23s warm, and each view imports ~30 more modules
 * that pay the same cost on their first request. That is the delay.
 *
 * Fetching the chunk *before* the click removes the wait rather than hiding it.
 * By the time the router asks for the module the browser already has it, so the
 * import resolves from cache and navigation is immediate.
 *
 * Two triggers
 * ------------
 * - **Intent** (`prefetchRoute`, on hover/focus): the strongest possible signal
 *   short of a click, and it costs one chunk.
 * - **Idle** (`prefetchRoutesWhenIdle`): warms the primary nav once the browser
 *   has nothing better to do, so even a first click on an unhovered item — a
 *   keyboard user hitting Enter, a tap on a touchscreen where hover does not
 *   exist — is already warm.
 *
 * Both are best-effort and idempotent. A failed prefetch is forgotten so a
 * later attempt (or the real navigation) can retry; it never surfaces an error,
 * because a prefetch the user did not ask for must not be able to break the page
 * they are on.
 */

import { router } from '@/router'

// Paths whose loaders have been invoked. The browser's module cache is what
// actually dedupes the network work — this set just avoids re-walking route
// records and re-calling loaders on every mousemove across a nav item.
const started = new Set<string>()

/**
 * Start loading the component chunks for `path`. Returns immediately.
 *
 * Safe to call repeatedly and from event handlers.
 */
export function prefetchRoute(path: string): void {
  if (started.has(path)) return
  started.add(path)

  let matched
  try {
    matched = router.resolve(path).matched
  } catch {
    // Unresolvable path (a typo in a nav item). Nothing to warm, and this is
    // not the place to complain about it — the real navigation will 404.
    started.delete(path)
    return
  }

  for (const record of matched) {
    for (const raw of Object.values(record.components ?? {})) {
      // A lazy route stores the `() => import(...)` thunk itself, so calling it
      // is what kicks off the fetch. Functional components are also functions,
      // which is why the result is checked for thenable-ness before being used
      // and the whole thing is wrapped: every route in this app is lazy, and if
      // that ever stops being true a stray call must stay harmless.
      if (typeof raw !== 'function') continue
      try {
        const result = (raw as () => unknown)()
        if (result && typeof (result as PromiseLike<unknown>).then === 'function') {
          void (result as Promise<unknown>).catch(() => {
            started.delete(path)
          })
        }
      } catch {
        started.delete(path)
      }
    }
  }
}

/**
 * Warm `paths` once the browser is idle.
 *
 * Skipped entirely when the user has asked the browser to conserve data, or on
 * a connection slow enough that speculative downloads would compete with the
 * request they actually made. Prefetching is a latency trade paid in bandwidth;
 * on a 2G tether that trade is the wrong way round.
 */
export function prefetchRoutesWhenIdle(paths: string[]): void {
  if (!paths.length || shouldSkipSpeculativeWork()) return

  const warm = () => {
    // One per idle callback rather than a loop, so a long nav list can never
    // monopolise a single idle window.
    const next = paths.find((p) => !started.has(p))
    if (!next) return
    prefetchRoute(next)
    schedule(warm)
  }
  schedule(warm)
}

type IdleWindow = Window &
  typeof globalThis & {
    requestIdleCallback?: (cb: () => void, opts?: { timeout?: number }) => number
  }

function schedule(cb: () => void): void {
  const w = window as IdleWindow
  if (typeof w.requestIdleCallback === 'function') {
    w.requestIdleCallback(cb, { timeout: 2000 })
  } else {
    // Safari had no requestIdleCallback until 17. A plain timeout is a worse
    // citizen but still keeps this off the critical path after first paint.
    window.setTimeout(cb, 300)
  }
}

type ConnectionLike = { saveData?: boolean; effectiveType?: string }

function shouldSkipSpeculativeWork(): boolean {
  const connection = (navigator as Navigator & { connection?: ConnectionLike }).connection
  if (!connection) return false
  if (connection.saveData) return true
  return connection.effectiveType === 'slow-2g' || connection.effectiveType === '2g'
}

/** Test hook — forget which paths have been warmed. */
export function resetPrefetchCache(): void {
  started.clear()
}
