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
    class="h-14 flex items-center gap-2 px-3 sm:gap-3 sm:px-5 border-b border-border/60 dark:border-border/30 nf-glass sticky top-0 z-10"
  >
    <!-- Mobile-only hamburger -->
    <button
      type="button"
      class="md:hidden inline-flex items-center justify-center w-9 h-9 rounded-full text-fg-muted hover:bg-surface-hover hover:text-fg transition"
      :aria-label="t('common.menu')"
      @click="ui.toggleMobileNav()"
    >
      <Menu class="w-[18px] h-[18px]" aria-hidden="true" />
    </button>

    <!-- Desktop search field (iOS-style soft pill). -->
    <button
      type="button"
      class="hidden md:inline-flex items-center gap-2 h-9 px-3.5 rounded-full bg-muted/70 hover:bg-muted text-sm text-fg-muted hover:text-fg transition-colors w-full max-w-sm"
      :aria-label="$t('common.search')"
      @click="$emit('open-search')"
    >
      <Search class="w-[18px] h-[18px]" aria-hidden="true" />
      <span class="flex-1 text-left">{{ $t('common.search') }}…</span>
      <kbd
        class="hidden lg:inline-flex items-center gap-1 px-1.5 h-5 rounded-full text-[10px] font-mono bg-surface/80 text-fg-muted"
      >
        Ctrl K
      </kbd>
    </button>
    <!-- Mobile search icon-only -->
    <button
      type="button"
      class="md:hidden inline-flex items-center justify-center w-9 h-9 rounded-full text-fg-muted hover:bg-surface-hover hover:text-fg transition"
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
        class="inline-flex items-center gap-2 h-9 pl-1 pr-2.5 rounded-full hover:bg-surface-hover transition-colors"
        :aria-haspopup="true"
        :aria-expanded="menuOpen"
        @click="toggleMenu"
      >
        <!-- iOS-style avatar disc with a subtle gradient. Indigo brand tone
             keeps it visible against either bg. -->
        <span
          class="inline-flex items-center justify-center w-7 h-7 rounded-full bg-gradient-to-br from-primary-500 to-primary-700 text-white text-xs font-semibold"
          aria-hidden="true"
        >
          {{ initials || '—' }}
        </span>
        <span class="hidden md:flex flex-col items-start leading-tight">
          <span class="text-xs font-medium text-fg max-w-[10rem] truncate">
            {{ user?.display_name || user?.email || '—' }}
          </span>
          <span class="text-[10px] text-fg-muted">{{ roleLabel }}</span>
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
