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
  { display: '?', descriptionKey: 'shortcuts.descriptions.help' },
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
    i: '/import',
    a: '/audit',
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

    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault()
      handlers.onSearch()
      clearLeader()
      return
    }

    // No modifiers from here on — let Cmd-A, Alt-Tab, etc. through unchanged.
    if (e.metaKey || e.ctrlKey || e.altKey) return

    if (e.key === '?') {
      e.preventDefault()
      handlers.onHelp()
      clearLeader()
      return
    }

    if (e.key === '/') {
      e.preventDefault()
      handlers.onSearch()
      clearLeader()
      return
    }

    if (waitingForSecond) {
      const dest = NAV[e.key.toLowerCase()]
      if (dest) {
        e.preventDefault()
        router.push(dest)
      }
      clearLeader()
      return
    }

    if (e.key === 'g') {
      waitingForSecond = true
      // GitHub uses a ~1s window before the leader expires — same here.
      resetTimer = setTimeout(clearLeader, 1000)
    }
  }

  onMounted(() => window.addEventListener('keydown', onKey))
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onKey)
    clearLeader()
  })
}
