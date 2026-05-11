<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import Spinner from '@/components/ui/Spinner.vue'

const { status, isAuthenticated, consumePostLoginPath } = useAuth()
const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()

const isBooting = computed(() => status.value === 'idle' || status.value === 'loading')

watch(
  [() => route.meta.titleKey, locale],
  ([titleKey]) => {
    const appName = t('app.name')
    document.title = titleKey ? `${t(String(titleKey))} · ${appName}` : appName
  },
  { immediate: true },
)

// Honor the post-login `next` path stashed by LoginView before the OAuth dance.
// The backend hard-redirects to "/" after /auth/callback (see backend/app/routers/auth.py),
// so we restore the original destination on the first authenticated render.
watch(isAuthenticated, (auth) => {
  if (!auth) return
  const next = consumePostLoginPath()
  if (next && next !== route.fullPath && next !== '/') {
    router.replace(next)
  }
})
</script>

<template>
  <div v-if="isBooting" class="min-h-screen flex items-center justify-center">
    <Spinner :label="t('auth.loadingSession')" />
  </div>
  <RouterView v-else />
</template>
