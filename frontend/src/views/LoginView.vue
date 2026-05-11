<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { LogIn } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import BrandMark from '@/components/BrandMark.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import LocaleSwitcher from '@/components/LocaleSwitcher.vue'
import { useAuth } from '@/composables/useAuth'

// The backend hard-codes a single configured auth provider (AUTH_PROVIDER=github|oidc)
// and exposes the start-of-flow URL at /api/auth/login. The SPA can't (yet) introspect
// which provider is in use, so we read it from a build-time hint and fall back to "default".
const provider = (import.meta.env.VITE_AUTH_PROVIDER as string | undefined) || 'default'
const appVersion = (import.meta.env.VITE_APP_VERSION as string | undefined) ?? '0.1.0'
const { isAuthenticated, startLogin } = useAuth()
const route = useRoute()
const router = useRouter()
const { t } = useI18n()

// If the user lands on /login while already authenticated, bounce them home.
onMounted(() => {
  if (isAuthenticated.value) router.replace('/')
})

const providerLabel = computed(() => {
  const key = `auth.providers.${provider}`
  const translated = t(key)
  // vue-i18n returns the key itself when missing — fall back to the generic label.
  return translated === key ? t('auth.providers.default') : translated
})

function signIn() {
  const next = (route.query.next as string | undefined) || undefined
  startLogin(next)
}
</script>

<template>
  <div class="min-h-screen flex flex-col bg-bg text-fg">
    <header class="flex items-center justify-between p-4">
      <BrandMark />
      <div class="flex items-center gap-2">
        <LocaleSwitcher />
        <ThemeToggle />
      </div>
    </header>

    <main class="flex-1 flex items-center justify-center px-4">
      <div class="w-full max-w-sm">
        <div class="nf-card p-8">
          <div class="flex flex-col items-center text-center gap-2 mb-6">
            <BrandMark :show-wordmark="false" :size="44" />
            <h1 class="text-xl font-semibold tracking-tight">{{ $t('app.name') }}</h1>
            <p class="text-sm text-fg-muted">{{ $t('app.tagline') }}</p>
          </div>

          <p class="text-sm text-fg-muted text-center mb-5">
            {{ $t('auth.signInPrompt') }}
          </p>

          <Button variant="primary" size="lg" block @click="signIn">
            <LogIn class="w-4 h-4" aria-hidden="true" />
            {{ $t('auth.signInWith', { provider: providerLabel }) }}
          </Button>
        </div>

        <p class="mt-4 text-center text-xs text-fg-muted">NetForge · v{{ appVersion }}</p>
      </div>
    </main>
  </div>
</template>
