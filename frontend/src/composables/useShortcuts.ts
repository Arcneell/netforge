import { onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'

/**
 * Global keyboard shortcut spec — used both by the listener and by the help
 * overlay so the displayed list and the live binding never drift apart.
 *
 * `g <letter>` is a two-key sequence à la Vim/GitHub: press `g`, then the
 * second key within ~1s. Single-key entries (Cmd+K, ?, /) fire immediately.
 *
 * Keys are intentionally i18n'd at render time — descriptionKey resolves to
 * the FR/EN string in `shortcuts.descriptions.*`.
 */
export interface Shortcut {
  /** Display key, e.g. "g d", "?". */
  display: string
  descriptionKey: string
}

export const SHORTCUTS: Shortcut[] = [
  { display: '⌘ K / Ctrl K', descriptionKey: 'shortcuts.descriptions.search' },
  { display: '? / F1', descriptionKey: 'shortcuts.descriptions.help' },
  { display: 'g d', descriptionKey: 'shortcuts.descriptions.goDashboard' },
  { display: 'g s', descriptionKey: 'shortcuts.descriptions.goSubnets' },
  { display: 'g v', descriptionKey: 'shortcuts.descriptions.goVlans' },
  { display: 'g w', descriptionKey: 'shortcuts.descriptions.goSwitches' },
  { display: 'g e', descriptionKey: 'shortcuts.descriptions.goDevices' },
  { display: 'g t', descriptionKey: 'shortcuts.descriptions.goTopology' },
  { display: 'g i', descriptionKey: 'shortcuts.descriptions.goImport' },
  { display: 'g a', descriptionKey: 'shortcuts.descriptions.goAudit' },
]

interface Handlers {
  onSearch: () => void
  onHelp: () => void
}

function isTypingTarget(target: EventTarget | null): boolean {
  // We never swallow keystrokes that are headed for an input/contenteditable —
  // typing "g" in the search box must keep showing the letter, not navigate.
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (el.isContentEditable) return true
  return false
}

/**
 * Layout-resilient match for "?". On QWERTY US `?` is Shift+/ (physical key
 * Slash); on AZERTY FR `?` is Shift+, (physical key Comma). e.key alone is
 * unreliable across layouts in some browser/OS combos, so we ALSO match by
 * e.code — the physical key location — and finally by F1 as a universal
 * help shortcut.
 */
function isHelpShortcut(e: KeyboardEvent): boolean {
  if (e.key === 'F1') return true
  if (e.key === '?') return true
  if (e.shiftKey && (e.code === 'Slash' || e.code === 'Comma')) return true
  return false
}

export function useGlobalShortcuts(handlers: Handlers): void {
  const router = useRouter()
  // Two-key combos like "g d" — track the first keypress and a short timeout.
  let waitingForSecond = false
  let resetTimer: ReturnType<typeof setTimeout> | null = null

  const NAV: Record<string, string> = {
    d: '/',
    s: '/subnets',
    v: '/vlans',
    w: '/switches',
    e: '/devices',
    t: '/topology',
    i: '/data/import',
    a: '/data/audit',
  }

  function clearLeader() {
    waitingForSecond = false
    if (resetTimer) {
      clearTimeout(resetTimer)
      resetTimer = null
    }
  }

  function onKey(e: KeyboardEvent) {
    if (isTypingTarget(e.target)) return

    // Cmd/Ctrl K — opens the search palette.
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault()
      handlers.onSearch()
      clearLeader()
      return
    }

    // F1 deserves to work alongside Ctrl/Cmd, so check help BEFORE the
    // modifier short-circuit below.
    if (isHelpShortcut(e)) {
      e.preventDefault()
      handlers.onHelp()
      clearLeader()
      return
    }

    // No modifiers from here on — let Cmd-A, Alt-Tab, etc. through unchanged.
    if (e.metaKey || e.ctrlKey || e.altKey) return

    if (e.key === '/') {
      e.preventDefault()
      handlers.onSearch()
      clearLeader()
      return
    }

    // Resolve the second key of a g-leader sequence by lowercased character —
    // Caps Lock yields 'T' which `'t'.toLowerCase()` covers.
    if (waitingForSecond) {
      // Always clear the leader BEFORE we navigate. The previous order
      // (push → clearLeader) left the 1.5s reset timer alive while the
      // new view was mounting; a 'd' typed on the new page during that
      // window resolved to '/' and navigated back. Clear the leader +
      // its timer first, then dispatch.
      clearLeader()
      const dest = NAV[e.key.toLowerCase()]
      if (dest && router.currentRoute.value.path !== dest) {
        e.preventDefault()
        void router.push(dest)
      } else if (dest) {
        // Already on the destination — swallow the key so it doesn't
        // also act as a default in any focused widget, but don't fire
        // a redundant navigation.
        e.preventDefault()
      }
      return
    }

    // Same lowercase trick for the leader itself: 'G' under Caps Lock should
    // still start a sequence.
    if (e.key === 'g' || e.key === 'G') {
      // Don't preventDefault — `g` has no browser default and preventDefault
      // here would block "g" from being typed in non-input focusable widgets
      // like contenteditable cells we might introduce later.
      waitingForSecond = true
      // GitHub uses a ~1s window before the leader expires — same here.
      if (resetTimer) clearTimeout(resetTimer)
      resetTimer = setTimeout(clearLeader, 1500)
    }
  }

  onMounted(() => window.addEventListener('keydown', onKey))
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onKey)
    clearLeader()
  })
}
