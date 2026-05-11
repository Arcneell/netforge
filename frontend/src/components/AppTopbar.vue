<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Search, LogOut, ChevronDown } from 'lucide-vue-next'
import { useAuth } from '@/composables/useAuth'
import ThemeToggle from '@/components/ThemeToggle.vue'
import LocaleSwitcher from '@/components/LocaleSwitcher.vue'

const { t } = useI18n()
const { user, role, logout } = useAuth()
const menuOpen = ref(false)

const initials = computed(() => {
  const name = user.value?.display_name || user.value?.email || '?'
  return name
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('')
})

const roleLabel = computed(() => {
  if (role.value === 'admin') return t('user.role.admin')
  if (role.value === 'viewer') return t('user.role.viewer')
  return ''
})

function toggleMenu() {
  menuOpen.value = !menuOpen.value
}

async function onLogout() {
  menuOpen.value = false
  await logout()
  window.location.href = '/login'
}
</script>

<template>
  <header
    class="h-14 flex items-center gap-3 px-4 border-b border-border bg-surface/80 backdrop-blur sticky top-0 z-10"
  >
    <!-- Global search trigger (placeholder for Phase 10 cmd+k panel) -->
    <button
      type="button"
      class="hidden md:inline-flex items-center gap-2 h-9 px-3 rounded-md border border-border bg-bg/60 text-sm text-fg-muted hover:bg-surface-hover transition w-full max-w-sm"
      :aria-label="$t('common.search')"
      disabled
    >
      <Search class="w-4 h-4" aria-hidden="true" />
      <span class="flex-1 text-left">{{ $t('common.search') }}…</span>
      <kbd
        class="hidden lg:inline-flex items-center gap-1 px-1.5 h-5 rounded text-[10px] font-mono border border-border bg-muted/60"
      >
        Ctrl K
      </kbd>
    </button>
    <div class="flex-1" />

    <LocaleSwitcher />
    <ThemeToggle />

    <div class="relative">
      <button
        type="button"
        class="inline-flex items-center gap-2 h-9 pl-1 pr-2 rounded-md border border-border bg-surface hover:bg-surface-hover transition"
        :aria-haspopup="true"
        :aria-expanded="menuOpen"
        @click="toggleMenu"
      >
        <span
          class="inline-flex items-center justify-center w-7 h-7 rounded-md bg-primary-100 text-primary-700 text-xs font-semibold dark:bg-primary-100/30 dark:text-primary-50"
          aria-hidden="true"
        >
          {{ initials || '—' }}
        </span>
        <span class="hidden md:flex flex-col items-start leading-tight">
          <span class="text-xs font-medium text-fg max-w-[10rem] truncate">
            {{ user?.display_name || user?.email || '—' }}
          </span>
          <span class="text-[10px] text-fg-muted uppercase tracking-wide">{{ roleLabel }}</span>
        </span>
        <ChevronDown class="w-4 h-4 text-fg-muted" aria-hidden="true" />
      </button>

      <Transition
        enter-active-class="transition duration-100 ease-out"
        enter-from-class="opacity-0 translate-y-1"
        enter-to-class="opacity-100 translate-y-0"
        leave-active-class="transition duration-75 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div
          v-if="menuOpen"
          class="absolute right-0 mt-2 w-60 nf-card shadow-pop p-1 z-20"
          role="menu"
          @click.stop
        >
          <div class="px-3 py-2 border-b border-border">
            <p class="text-[10px] uppercase tracking-wide text-fg-muted">
              {{ $t('user.menu.signedInAs') }}
            </p>
            <p class="text-sm font-medium text-fg truncate">{{ user?.email || '—' }}</p>
            <p class="text-xs text-fg-muted">{{ roleLabel }}</p>
          </div>
          <button
            type="button"
            class="w-full mt-1 inline-flex items-center gap-2 px-3 py-2 rounded text-sm text-fg-muted hover:bg-surface-hover hover:text-fg transition"
            role="menuitem"
            @click="onLogout"
          >
            <LogOut class="w-4 h-4" aria-hidden="true" />
            {{ $t('auth.signOut') }}
          </button>
        </div>
      </Transition>
    </div>

    <!-- Click-away guard -->
    <div v-if="menuOpen" class="fixed inset-0 z-10" aria-hidden="true" @click="menuOpen = false" />
  </header>
</template>
