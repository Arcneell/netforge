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
    <header class="flex items-center justify-between px-6 h-16">
      <BrandMark />
      <div class="flex items-center gap-2">
        <LocaleSwitcher />
        <ThemeToggle />
      </div>
    </header>

    <main class="flex-1 flex items-center justify-center px-4 pb-16">
      <div class="w-full max-w-[22rem] nf-enter">
        <div class="text-center">
          <BrandMark :show-wordmark="false" :size="48" class="mx-auto" />
          <h1 class="text-2xl font-semibold tracking-[-0.02em] mt-5">{{ $t('app.name') }}</h1>
          <p class="text-base text-fg-muted mt-1.5">{{ $t('app.tagline') }}</p>
        </div>

        <!-- The card holds only the action. Identity lives above it, on the
             page, which keeps the one thing you came here to do unmissable. -->
        <div class="nf-card p-6 mt-8">
          <p class="text-base text-fg-muted text-center">{{ $t('auth.signInPrompt') }}</p>
          <Button variant="primary" size="lg" block class="mt-5" @click="signIn">
            <LogIn class="w-4 h-4" aria-hidden="true" />
            {{ $t('auth.signInWith', { provider: providerLabel }) }}
          </Button>
        </div>

        <p class="mt-6 text-center text-xs text-fg-subtle">v{{ appVersion }}</p>
      </div>
    </main>
  </div>
</template>
