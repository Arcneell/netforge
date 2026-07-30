<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Search, LogOut, ChevronDown, Menu } from '@lucide/vue'
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
  <!-- 52px, not 64: this is an instrument strip, and the height it doesn't take
       goes to the data below it. -->
  <header
    class="h-[3.25rem] flex items-center gap-2 px-3 sm:gap-3 sm:px-5 border-b border-border bg-bg sticky top-0 z-20 flex-shrink-0"
  >
    <!-- Mobile-only hamburger -->
    <button
      type="button"
      class="md:hidden inline-flex items-center justify-center w-9 h-9 rounded-md text-fg-muted hover:bg-surface-hover hover:text-fg transition-colors duration-150 ease-panel"
      :aria-label="t('common.menu')"
      @click="ui.toggleMobileNav()"
    >
      <Menu class="w-[18px] h-[18px]" aria-hidden="true" />
    </button>

    <!-- Desktop search. A milled slot: recessed and square, looking like the
         field it opens so the shortcut is discoverable without a tour. -->
    <button
      type="button"
      class="hidden md:inline-flex items-center gap-2.5 h-8 px-2.5 rounded-md w-full max-w-sm bg-surface border border-border-strong shadow-inset text-fg-subtle hover:text-fg-muted hover:border-fg-subtle transition-colors duration-150 ease-panel"
      :aria-label="$t('common.search')"
      @click="$emit('open-search')"
    >
      <Search class="w-3.5 h-3.5 flex-shrink-0" aria-hidden="true" />
      <span class="flex-1 text-left text-base truncate">{{ $t('common.search') }}…</span>
      <kbd class="hidden lg:inline-flex items-center px-1.5 h-5 rounded nf-legend bg-muted">
        Ctrl K
      </kbd>
    </button>
    <!-- Mobile search icon-only -->
    <button
      type="button"
      class="md:hidden inline-flex items-center justify-center w-9 h-9 rounded-md text-fg-muted hover:bg-surface-hover hover:text-fg transition-colors duration-150 ease-panel"
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
        class="inline-flex items-center gap-2 h-8 pl-1 pr-1.5 rounded-md hover:bg-surface-hover transition-colors duration-150 ease-panel"
        :aria-haspopup="true"
        :aria-expanded="menuOpen"
        @click="toggleMenu"
      >
        <!-- Square, not a circle. An avatar circle is the one shape that says
             "social product"; a stamped square plate says "this is an operator
             account on a piece of equipment". -->
        <span
          class="inline-flex items-center justify-center w-6 h-6 rounded bg-plate text-plate-fg font-mono text-2xs font-semibold tracking-tight"
          aria-hidden="true"
        >
          {{ initials || '—' }}
        </span>
        <span class="hidden md:inline text-sm font-medium text-fg max-w-[10rem] truncate">
          {{ user?.display_name || user?.email || '—' }}
        </span>
        <ChevronDown class="w-3.5 h-3.5 text-fg-subtle" aria-hidden="true" />
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
          class="absolute right-0 mt-1.5 w-60 bg-surface border border-border-strong rounded-lg shadow-lg p-1 z-20"
          role="menu"
          @click.stop
        >
          <div class="px-2.5 py-2">
            <p class="nf-legend mb-1">{{ roleLabel }}</p>
            <p class="text-base font-medium text-fg truncate">{{ user?.email || '—' }}</p>
          </div>
          <hr class="my-1 border-border" />
          <button
            type="button"
            class="w-full inline-flex items-center gap-2 px-2.5 py-2 rounded-md text-base text-fg-muted hover:bg-surface-hover hover:text-fg transition-colors duration-150 ease-panel"
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
