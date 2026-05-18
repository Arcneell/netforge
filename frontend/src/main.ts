import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from '@/App.vue'
import { router } from '@/router'
import { i18n, setLocale } from '@/i18n'
import { registerApiHooks } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

// Self-hosted Geist Sans + Mono. We pull only the weights actually used:
// 400 (body), 500 (medium emphasis), 600 (semibold titles). Mono ships in
// 400 + 500 — that's enough for IDs / CIDRs / MACs. Each extra weight is
// ~30KB so we resist the urge to import the whole family.
import '@fontsource/geist-sans/400.css'
import '@fontsource/geist-sans/500.css'
import '@fontsource/geist-sans/600.css'
import '@fontsource/geist-mono/400.css'
import '@fontsource/geist-mono/500.css'

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

app.mount('#app')
