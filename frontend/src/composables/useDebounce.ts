import { onScopeDispose, ref, watch, type Ref } from 'vue'

/**
 * Debounce a reactive source. The returned ref settles `delayMs` ms after the
 * source last changed.
 *
 * Lifecycle: the pending setTimeout is cancelled on scope disposal
 * (`onScopeDispose`) so a component unmounting mid-keystroke never fires a
 * stale write into a ref of the destroyed scope. Without this, downstream
 * watchers can race against `load()` calls on unmounted views and surface
 * confusing "Cannot read properties of null" toasts.
 *
 * `flush()` lets the caller force the pending value through immediately —
 * useful for "clear filters" UX where the next `load()` must see the cleared
 * query, not the previous one waiting on its 200 ms timer.
 */
export interface Debounced<T> {
  /** Reactive debounced value — same shape as the source. */
  value: T
  /** Force-settle the pending value and cancel the timer. */
  flush: () => void
}

export function useDebounce<T>(source: Ref<T>, delayMs = 250): Ref<T> & { flush: () => void } {
  const debounced = ref(source.value) as Ref<T>
  let timer: ReturnType<typeof setTimeout> | null = null
  let pending: T | undefined

  function clear() {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  function flush() {
    if (timer && pending !== undefined) {
      debounced.value = pending as T
    }
    clear()
    pending = undefined
  }

  watch(source, (value) => {
    pending = value
    clear()
    timer = setTimeout(() => {
      debounced.value = value
      timer = null
      pending = undefined
    }, delayMs)
  })

  onScopeDispose(clear)

  // Attach `flush` to the returned ref so callers can invoke it without
  // changing the destructure pattern used across the codebase.
  return Object.assign(debounced, { flush })
}
