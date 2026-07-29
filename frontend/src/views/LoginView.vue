<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { LogIn } from 'lucide-vue-next'
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
    <!-- No brand mark up here: the plate below carries the identity, and showing
         it twice on a page with one action is just noise. -->
    <header class="flex items-center justify-end px-6 h-[3.25rem]">
      <div class="flex items-center gap-2">
        <LocaleSwitcher />
        <ThemeToggle />
      </div>
    </header>

    <main class="flex-1 flex items-center justify-center px-4 pb-20">
      <div class="w-full max-w-[23rem] nf-enter">
        <!-- The front panel. Identity and the single action on one engraved
             plate, legends left-aligned the way they are on real equipment —
             the centred stack is the shape every SaaS login already has. -->
        <div class="nf-plate-lip bg-plate text-plate-fg border border-plate-border rounded-lg">
          <div class="px-6 pt-6 pb-5">
            <BrandMark :size="34" on-plate />
            <p class="text-base text-plate-fg-muted mt-4">{{ $t('app.tagline') }}</p>
          </div>

          <!-- The action sits below the plate's own hairline: everything above
               tells you where you are, everything below is what you do. -->
          <div class="px-6 pb-6 pt-5 border-t border-plate-border">
            <button
              type="button"
              class="w-full inline-flex items-center justify-center gap-2 h-10 px-4 rounded-md bg-primary-600 hover:bg-primary-500 active:translate-y-px text-white text-base font-medium transition-[background-color,transform] duration-150 ease-panel"
              @click="signIn"
            >
              <LogIn class="w-4 h-4" aria-hidden="true" />
              {{ $t('auth.signInWith', { provider: providerLabel }) }}
            </button>
          </div>
        </div>

        <!-- Spelled out rather than "v0.1.0": the legend style uppercases, and
             "V0.1.0" reads as a typo. -->
        <p class="nf-legend mt-4">Version {{ appVersion }}</p>
      </div>
    </main>
  </div>
</template>
