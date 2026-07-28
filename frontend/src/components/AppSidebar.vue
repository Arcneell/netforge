<script setup lang="ts">
import { computed, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  Database,
  LayoutGrid,
  Network,
  Tags,
  Router as RouterIcon,
  Server,
  Share2,
  Settings,
  Sparkles,
  X,
} from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { useUiStore } from '@/stores/ui'
import { useAuth } from '@/composables/useAuth'
import BrandMark from '@/components/BrandMark.vue'

interface NavItem {
  to: string
  icon: typeof LayoutGrid
  labelKey: string
  adminOnly?: boolean
  /** Draw a separator above this item. */
  startsGroup?: boolean
  /** Small trailing tag, e.g. to flag a section that is being rebuilt. */
  badgeKey?: string
}

// One flat list. The six network objects are what people reach for all day and
// each stays one click away; everything administrative collapses into two
// workspaces ("Assistant", "Données") that carry their own tabs. Thirteen
// entries and three section captions became nine entries and one rule.
const items: NavItem[] = [
  { to: '/', icon: LayoutGrid, labelKey: 'nav.dashboard' },
  { to: '/subnets', icon: Network, labelKey: 'nav.subnets' },
  { to: '/vlans', icon: Tags, labelKey: 'nav.vlans' },
  { to: '/switches', icon: RouterIcon, labelKey: 'nav.switches' },
  { to: '/devices', icon: Server, labelKey: 'nav.devices' },
  { to: '/topology', icon: Share2, labelKey: 'nav.topology', badgeKey: 'common.wip' },
  {
    to: '/assistant',
    icon: Sparkles,
    labelKey: 'nav.assistant',
    adminOnly: true,
    startsGroup: true,
  },
  { to: '/data', icon: Database, labelKey: 'nav.data', adminOnly: true },
  { to: '/settings', icon: Settings, labelKey: 'nav.settings', adminOnly: true },
]

const ui = useUiStore()
const { sidebarCollapsed, mobileNavOpen } = storeToRefs(ui)
const { isAdmin } = useAuth()
const route = useRoute()

const visibleItems = computed(() => items.filter((i) => !i.adminOnly || isAdmin.value))

// Close the mobile drawer whenever the user navigates — otherwise tapping a
// nav item just toggles the route under a still-open overlay.
watch(
  () => route.path,
  () => {
    if (mobileNavOpen.value) ui.setMobileNavOpen(false)
  },
)
</script>

<template>
  <!-- Mobile-only backdrop. Clicking it dismisses the drawer; the sidebar
       itself is `position: fixed` on mobile so it floats over the content. -->
  <Transition
    enter-active-class="transition-opacity duration-150"
    enter-from-class="opacity-0"
    enter-to-class="opacity-100"
    leave-active-class="transition-opacity duration-100"
    leave-from-class="opacity-100"
    leave-to-class="opacity-0"
  >
    <div
      v-if="mobileNavOpen"
      class="md:hidden fixed inset-0 bg-zinc-900/30 dark:bg-black/60 z-30"
      aria-hidden="true"
      @click="ui.setMobileNavOpen(false)"
    />
  </Transition>

  <aside
    :class="[
      'flex flex-col bg-bg border-r border-border transition-transform duration-200 md:transition-[width]',
      'fixed md:static inset-y-0 left-0 z-40 w-64 md:w-auto',
      sidebarCollapsed ? 'md:w-[4.25rem]' : 'md:w-60',
      mobileNavOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0',
    ]"
    aria-label="Primary"
  >
    <div
      :class="[
        'h-16 flex items-center',
        sidebarCollapsed ? 'md:justify-center md:px-2 px-6' : 'px-6',
      ]"
    >
      <BrandMark :show-wordmark="!sidebarCollapsed || mobileNavOpen" :size="26" />
      <button
        type="button"
        class="md:hidden ml-auto inline-flex items-center justify-center w-8 h-8 rounded-md text-fg-muted hover:bg-surface-hover hover:text-fg transition-colors duration-150 ease-soft"
        aria-label="Close navigation"
        @click="ui.setMobileNavOpen(false)"
      >
        <X class="w-4 h-4" aria-hidden="true" />
      </button>
    </div>

    <nav class="flex-1 overflow-y-auto pb-4 px-3">
      <ul class="space-y-0.5">
        <template v-for="item in visibleItems" :key="item.to">
          <li v-if="item.startsGroup" aria-hidden="true" class="py-2.5">
            <hr class="border-border" :class="sidebarCollapsed ? 'md:mx-1' : 'mx-1'" />
          </li>
          <li>
            <RouterLink v-slot="{ href, navigate, isActive, isExactActive }" :to="item.to" custom>
              <a
                :href="href"
                :class="[
                  'group flex items-center gap-2.5 h-9 rounded-md text-base transition-colors duration-150 ease-soft',
                  sidebarCollapsed ? 'px-3 md:justify-center md:px-0' : 'px-3',
                  (item.to === '/' ? isExactActive : isActive)
                    ? 'bg-primary-50 text-primary-700 font-medium dark:bg-primary-500/15 dark:text-primary-300'
                    : 'text-fg-muted font-normal hover:bg-surface-hover hover:text-fg',
                ]"
                :title="sidebarCollapsed ? $t(item.labelKey) : undefined"
                :aria-current="(item.to === '/' ? isExactActive : isActive) ? 'page' : undefined"
                @click="navigate"
              >
                <component
                  :is="item.icon"
                  class="w-[17px] h-[17px] flex-shrink-0"
                  :stroke-width="1.9"
                  aria-hidden="true"
                />
                <span class="truncate" :class="sidebarCollapsed ? 'md:hidden' : ''">
                  {{ $t(item.labelKey) }}
                </span>
                <span
                  v-if="item.badgeKey"
                  class="ml-auto text-2xs font-medium px-1.5 py-0.5 rounded bg-warning/10 text-warning"
                  :class="sidebarCollapsed ? 'md:hidden' : ''"
                >
                  {{ $t(item.badgeKey) }}
                </span>
              </a>
            </RouterLink>
          </li>
        </template>
      </ul>
    </nav>

    <!-- Desktop only: collapse / expand toggle. On mobile the user closes the
         drawer via the X in the header or the backdrop tap. -->
    <div :class="['hidden md:block p-3 pt-0']">
      <button
        type="button"
        class="w-full inline-flex items-center justify-center h-8 rounded-md text-fg-subtle hover:bg-surface-hover hover:text-fg transition-colors duration-150 ease-soft"
        :aria-label="sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'"
        @click="ui.toggleSidebar()"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          class="w-4 h-4"
          :class="sidebarCollapsed ? 'rotate-180' : ''"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="m15 6-6 6 6 6" />
        </svg>
      </button>
    </div>
  </aside>
</template>
