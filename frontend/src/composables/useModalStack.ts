/**
 * Module-scope LIFO stack of currently-open modal instances.
 *
 * Without this, every Modal instance attached its own window-level
 * keydown handler that only guarded on `props.open`. When two modals
 * were open simultaneously (e.g. WebhooksSection mounts editor +
 * deliveries + ConfirmDialog as siblings), every keydown hit BOTH
 * handlers:
 *
 *   - Escape on the inner modal emitted `close` from both, dismissing
 *     the outer one the user wanted to keep.
 *   - Tab in the inner modal — the outer Modal's focus-trap saw
 *     `document.activeElement` outside its `dialogRef` and yanked
 *     focus back to its own last focusable, defeating the trap.
 *
 * The ref-counted scroll-lock (`useScrollLock`) actively encourages
 * modal stacking by fixing the body-overflow bug, so this surfaces
 * easily in normal flows.
 *
 * Contract:
 *   const id = Symbol('modal')
 *   onOpen:  pushModal(id)
 *   onClose: popModal(id)
 *   in keydown handler: if (!isTopmostModal(id)) return
 *
 * The stack is process-global because there's only one `document` —
 * cross-component coordination of "which modal is on top" can't live
 * inside any single instance.
 */

const _stack: symbol[] = []

export function pushModal(id: symbol): void {
  if (!_stack.includes(id)) _stack.push(id)
}

export function popModal(id: symbol): void {
  const idx = _stack.lastIndexOf(id)
  if (idx >= 0) _stack.splice(idx, 1)
}

export function isTopmostModal(id: symbol): boolean {
  return _stack.length > 0 && _stack[_stack.length - 1] === id
}
