/**
 * Ref-counted body scroll-lock.
 *
 * The Modal component used to set `body.style.overflow = 'hidden'` on open
 * and `''` on close — fine for one modal, broken when modals stack (a
 * ConfirmDialog opened from inside an editor modal such as SiteEditor or
 * RoomEditor, the WebhooksSection's editor + deliveries + ConfirmDialog
 * mounted with separate `:open` flags, etc.). Closing the inner modal
 * cleared the lock while the outer was still visible, and the page scrolled
 * behind it.
 *
 * This composable counts active locks at module scope. The body's overflow
 * style is set on the 0→1 transition and cleared on the 1→0 transition, so
 * the inner modal closing keeps the lock alive for the outer one.
 *
 * Caller contract: invoke `useScrollLock()` once per modal instance; pass
 * the `:open` ref to `useScrollLock(open)`. The composable wires up watcher
 * and cleanup so unmount mid-open releases the lock exactly once.
 */
import { onBeforeUnmount, watch, type Ref } from 'vue'

// Module-scope ref count. Module singletons are unavoidable here — the
// document body is shared.
let _lockCount = 0
let _previousOverflow = ''

function acquire(): void {
  if (_lockCount === 0) {
    _previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  _lockCount += 1
}

function release(): void {
  if (_lockCount <= 0) {
    // Defensive: never go negative even if a caller misuses the API.
    _lockCount = 0
    return
  }
  _lockCount -= 1
  if (_lockCount === 0) {
    document.body.style.overflow = _previousOverflow
    _previousOverflow = ''
  }
}

export function useScrollLock(active: Ref<boolean>): void {
  let held = false

  function set(open: boolean) {
    if (open && !held) {
      acquire()
      held = true
    } else if (!open && held) {
      release()
      held = false
    }
  }

  watch(active, set, { immediate: true })

  onBeforeUnmount(() => {
    if (held) {
      release()
      held = false
    }
  })
}
