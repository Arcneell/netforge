import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { setLocale, type Locale, SUPPORTED_LOCALES } from '@/i18n'

export type Theme = 'light' | 'dark' | 'system'
export type ToastKind = 'info' | 'success' | 'warning' | 'error'

export interface Toast {
  id: number
  kind: ToastKind
  title?: string
  message: string
  timeout: number
}

const THEME_KEY = 'netforge.theme'

function readStoredTheme(): Theme {
  try {
    const v = localStorage.getItem(THEME_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    // ignore
  }
  return 'system'
}

function prefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

function applyTheme(theme: Theme): void {
  const isDark = theme === 'dark' || (theme === 'system' && prefersDark())
  document.documentElement.classList.toggle('dark', isDark)
  document.documentElement.dataset.theme = isDark ? 'dark' : 'light'
}

// Module-scope listener handle so we only register the system-theme
// matchMedia change listener ONCE per process. The store factory used to
// add it on every `useUiStore()` call, which accumulated listeners over
// HMR reloads and Pinia store-recreation in tests.
let _systemThemeListenerAttached = false
let _currentTheme: { value: Theme } | null = null
function _onSystemThemeChange(): void {
  if (_currentTheme && _currentTheme.value === 'system') applyTheme('system')
}

export const useUiStore = defineStore('ui', () => {
  const theme = ref<Theme>(readStoredTheme())
  // Module-level handle on the current theme so the matchMedia listener
  // (registered once at first store creation) always reads the live value.
  _currentTheme = theme
  const sidebarCollapsed = ref<boolean>(false)
  // Slide-in mobile drawer state. Separate from `sidebarCollapsed` because on
  // desktop a collapsed sidebar still shows icons, whereas on mobile the
  // sidebar is fully hidden until the hamburger button opens the drawer.
  const mobileNavOpen = ref<boolean>(false)
  const toasts = ref<Toast[]>([])
  let nextToastId = 1

  // Keep the html.dark class in sync with the system preference when in `system` mode.
  // Module-level guard so re-creating the store across HMR / test mounts
  // doesn't accumulate listeners (each previous one would keep its closure
  // over the now-stale `theme` ref alive).
  if (typeof window !== 'undefined' && window.matchMedia && !_systemThemeListenerAttached) {
    _systemThemeListenerAttached = true
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', _onSystemThemeChange)
  }

  function setTheme(next: Theme): void {
    theme.value = next
    try {
      localStorage.setItem(THEME_KEY, next)
    } catch {
      // ignore
    }
    applyTheme(next)
  }

  const isDark = computed(
    () => theme.value === 'dark' || (theme.value === 'system' && prefersDark()),
  )

  function toggleTheme(): void {
    setTheme(isDark.value ? 'light' : 'dark')
  }

  function changeLocale(next: Locale): void {
    if (!SUPPORTED_LOCALES.includes(next)) return
    setLocale(next)
  }

  function pushToast(t: {
    kind: ToastKind
    title?: string
    message: string
    timeout?: number
    id?: number
  }): number {
    const id = t.id ?? nextToastId++
    const toast: Toast = {
      id,
      kind: t.kind,
      title: t.title,
      message: t.message,
      timeout: t.timeout ?? (t.kind === 'error' ? 6000 : 4000),
    }
    toasts.value.push(toast)
    if (toast.timeout > 0) {
      setTimeout(() => dismissToast(id), toast.timeout)
    }
    return id
  }

  function dismissToast(id: number): void {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  function setSidebarCollapsed(v: boolean): void {
    sidebarCollapsed.value = v
  }

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function setMobileNavOpen(v: boolean): void {
    mobileNavOpen.value = v
  }

  function toggleMobileNav(): void {
    mobileNavOpen.value = !mobileNavOpen.value
  }

  // Run once at store creation so the SSR-applied class stays in sync with state.
  applyTheme(theme.value)

  return {
    theme,
    isDark,
    sidebarCollapsed,
    mobileNavOpen,
    toasts,
    setTheme,
    toggleTheme,
    changeLocale,
    pushToast,
    dismissToast,
    setSidebarCollapsed,
    toggleSidebar,
    setMobileNavOpen,
    toggleMobileNav,
  }
})
