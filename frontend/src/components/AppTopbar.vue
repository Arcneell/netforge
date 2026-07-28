<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Search, LogOut, ChevronDown, Menu } from 'lucide-vue-next'
import { useAuth } from '@/composables/useAuth'
import { useUiStore } from '@/stores/ui'
import ThemeToggle from '@/components/ThemeToggle.vue'
import LocaleSwitcher from '@/components/LocaleSwitcher.vue'

const { t } = useI18n()
const { user, role, logout } = useAuth()
const ui = useUiStore()
const menuOpen = ref(false)

defineEmits<{ (e: 'open-search'): void }>()

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
    class="h-16 flex items-center gap-2 px-4 sm:gap-3 sm:px-6 border-b border-border bg-bg sticky top-0 z-20"
  >
    <!-- Mobile-only hamburger -->
    <button
      type="button"
      class="md:hidden inline-flex items-center justify-center w-9 h-9 rounded-md text-fg-muted hover:bg-surface-hover hover:text-fg transition-colors duration-150 ease-soft"
      :aria-label="t('common.menu')"
      @click="ui.toggleMobileNav()"
    >
      <Menu class="w-[18px] h-[18px]" aria-hidden="true" />
    </button>

    <!-- Desktop search. Looks like the field it opens, so the shortcut is
         discoverable without a tour. -->
    <button
      type="button"
      class="hidden md:inline-flex items-center gap-2.5 h-9 px-3 rounded-md w-full max-w-md text-base text-fg-subtle hover:text-fg-muted bg-surface border border-border hover:border-border-strong transition-colors duration-150 ease-soft"
      :aria-label="$t('common.search')"
      @click="$emit('open-search')"
    >
      <Search class="w-4 h-4 flex-shrink-0" aria-hidden="true" />
      <span class="flex-1 text-left">{{ $t('common.search') }}…</span>
      <kbd
        class="hidden lg:inline-flex items-center px-1.5 h-5 rounded text-2xs font-medium bg-muted text-fg-subtle"
      >
        Ctrl K
      </kbd>
    </button>
    <!-- Mobile search icon-only -->
    <button
      type="button"
      class="md:hidden inline-flex items-center justify-center w-9 h-9 rounded-md text-fg-muted hover:bg-surface-hover hover:text-fg transition-colors duration-150 ease-soft"
      :aria-label="$t('common.search')"
      @click="$emit('open-search')"
    >
      <Search class="w-[18px] h-[18px]" aria-hidden="true" />
    </button>
    <div class="flex-1" />

    <LocaleSwitcher />
    <ThemeToggle />

    <div class="relative">
      <button
        type="button"
        class="inline-flex items-center gap-2 h-9 pl-1 pr-2 rounded-md hover:bg-surface-hover transition-colors duration-150 ease-soft"
        :aria-haspopup="true"
        :aria-expanded="menuOpen"
        @click="toggleMenu"
      >
        <span
          class="inline-flex items-center justify-center w-7 h-7 rounded-full bg-primary-100 text-primary-700 text-2xs font-semibold dark:bg-primary-500/20 dark:text-primary-300"
          aria-hidden="true"
        >
          {{ initials || '—' }}
        </span>
        <span class="hidden md:inline text-sm font-medium text-fg max-w-[10rem] truncate">
          {{ user?.display_name || user?.email || '—' }}
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
          class="absolute right-0 mt-2 w-60 bg-surface border border-border rounded-lg shadow-lg p-1.5 z-20"
          role="menu"
          @click.stop
        >
          <div class="px-2.5 py-2">
            <p class="text-base font-medium text-fg truncate">{{ user?.email || '—' }}</p>
            <p class="text-xs text-fg-muted mt-0.5">{{ roleLabel }}</p>
          </div>
          <hr class="my-1.5 border-border" />
          <button
            type="button"
            class="w-full inline-flex items-center gap-2 px-2.5 py-2 rounded-md text-base text-fg-muted hover:bg-surface-hover hover:text-fg transition-colors duration-150 ease-soft"
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
