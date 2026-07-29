import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from '@/App.vue'
import { router } from '@/router'
import { i18n, setLocale } from '@/i18n'
import { registerApiHooks } from '@/api'
import { registerLocaleProvider } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

// Self-hosted type, three faces.
//
// Archivo is imported from `wdth.css` rather than the default entry point: that
// build carries the variable *width* axis (62%–125%), which `.nf-display` needs
// to reach the expanded cut the display type is built on. The wght-only build
// would silently render at normal width and the whole type system would lose
// its one point of contrast.
//
// IBM Plex Sans carries the body. IBM Plex Mono carries every legend and every
// code-like value (CIDRs, MACs, firmware strings) — 600 is loaded because the
// tracked-out uppercase legends need it to hold at 11px.
import '@fontsource-variable/archivo/wdth.css'
import '@fontsource-variable/ibm-plex-sans'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@fontsource/ibm-plex-mono/600.css'

import '@/assets/tailwind.css'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(i18n)

// Bridge the framework-free api/client.ts to Pinia + router. Centralizing
// 401/403 handling here avoids each view having to know how to react to them.
const auth = useAuthStore()
const ui = useUiStore()

registerApiHooks({
  onUnauthorized: () => {
    const wasAuthenticated = auth.isAuthenticated
    auth.setAnonymous()
    // Only force a redirect on mid-session expiry. The initial /me call also
    // 401s for anonymous visitors, but the router guard owns that path and
    // would race with this redirect otherwise.
    if (wasAuthenticated) {
      ui.pushToast({ kind: 'warning', message: i18n.global.t('auth.errors.unauthorized') })
      if (router.currentRoute.value.name !== 'login') {
        const next = router.currentRoute.value.fullPath
        router.replace({
          path: '/login',
          query: next && next !== '/' ? { next } : undefined,
        })
      }
    }
  },
  onForbidden: () => {
    ui.pushToast({ kind: 'error', message: i18n.global.t('auth.errors.forbidden') })
  },
  onNetworkError: () => {
    ui.pushToast({ kind: 'error', message: i18n.global.t('errors.network') })
  },
})

// Apply the stored locale to <html lang> on boot.
setLocale(i18n.global.locale.value)

// Feed the api/client interceptor the current i18n locale so every outgoing
// request carries Accept-Language. Reads the live ref each call — picks up
// language switches without needing a re-register.
registerLocaleProvider(() => i18n.global.locale.value)

app.mount('#app')
