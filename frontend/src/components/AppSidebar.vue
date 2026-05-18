<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import {
  LayoutDashboard,
  Network,
  Tags,
  Router as RouterIcon,
  Server,
  Share2,
  Upload,
  History,
  Settings,
} from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { useUiStore } from '@/stores/ui'
import { useAuth } from '@/composables/useAuth'
import BrandMark from '@/components/BrandMark.vue'

interface NavItem {
  to: string
  icon: typeof LayoutDashboard
  labelKey: string
}

interface NavSection {
  /** Translation key for the section header. Omit to render a flat section
   *  (no caption above the items) — used for the top-level Dashboard row. */
  titleKey?: string
  /** Only visible to admins. Hides the entire section for viewers, including
   *  the title — keeps the sidebar uncluttered for read-only users. */
  adminOnly?: boolean
  items: NavItem[]
}

// Sections rather than a flat list: the previous sidebar mixed network entities
// (subnets / vlans / switches / topology) with admin operations (import / audit
// / settings) in a single column. Grouping clarifies "where to go for X" and
// puts the destructive admin actions below the daily-use stuff. The order
// inside each section follows usage frequency, not alphabetical.
const sections: NavSection[] = [
  {
    // Dashboard is its own pseudo-section — no caption, sits at the top as the
    // landing spot.
    items: [{ to: '/', icon: LayoutDashboard, labelKey: 'nav.dashboard' }],
  },
  {
    titleKey: 'nav.sections.network',
    items: [
      { to: '/subnets', icon: Network, labelKey: 'nav.subnets' },
      { to: '/vlans', icon: Tags, labelKey: 'nav.vlans' },
      { to: '/switches', icon: RouterIcon, labelKey: 'nav.switches' },
      { to: '/devices', icon: Server, labelKey: 'nav.devices' },
      { to: '/topology', icon: Share2, labelKey: 'nav.topology' },
    ],
  },
  {
    titleKey: 'nav.sections.administration',
    adminOnly: true,
    items: [
      { to: '/import', icon: Upload, labelKey: 'nav.import' },
      { to: '/audit', icon: History, labelKey: 'nav.audit' },
      { to: '/settings', icon: Settings, labelKey: 'nav.settings' },
    ],
  },
]

const ui = useUiStore()
const { sidebarCollapsed } = storeToRefs(ui)
const { isAdmin } = useAuth()

const visibleSections = computed(() => sections.filter((s) => !s.adminOnly || isAdmin.value))
</script>

<template>
  <aside
    :class="[
      'flex flex-col bg-surface border-r border-border transition-[width] duration-200',
      sidebarCollapsed ? 'w-16' : 'w-60',
    ]"
    aria-label="Primary"
  >
    <div
      :class="[
        'h-14 flex items-center border-b border-border',
        sidebarCollapsed ? 'justify-center px-2' : 'px-4',
      ]"
    >
      <BrandMark :show-wordmark="!sidebarCollapsed" :size="26" />
    </div>

    <nav class="flex-1 overflow-y-auto py-3 px-2">
      <div v-for="(section, sIdx) in visibleSections" :key="sIdx" :class="[sIdx > 0 ? 'mt-4' : '']">
        <!--
          Section captions live on the left margin in expanded mode. Collapsed
          mode hides them (the user only sees icons, captions would just be
          tooltips with no anchor), but we keep a thin divider line so the
          three groups stay visually distinct even at 64 px wide.
        -->
        <p
          v-if="section.titleKey && !sidebarCollapsed"
          class="px-3 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-fg-muted"
        >
          {{ $t(section.titleKey) }}
        </p>
        <hr v-else-if="section.titleKey && sidebarCollapsed" class="mx-3 mb-1.5 border-border" />
        <ul class="space-y-0.5">
          <li v-for="item in section.items" :key="item.to">
            <RouterLink v-slot="{ href, navigate, isActive, isExactActive }" :to="item.to" custom>
              <a
                :href="href"
                :class="[
                  'group flex items-center gap-3 rounded-md text-sm font-medium transition',
                  sidebarCollapsed ? 'justify-center px-2 py-2' : 'px-3 py-2',
                  (item.to === '/' ? isExactActive : isActive)
                    ? 'bg-primary-50 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300'
                    : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
                ]"
                :title="sidebarCollapsed ? $t(item.labelKey) : undefined"
                :aria-label="$t(item.labelKey)"
                :aria-current="(item.to === '/' ? isExactActive : isActive) ? 'page' : undefined"
                @click="navigate"
              >
                <component
                  :is="item.icon"
                  class="w-[18px] h-[18px] flex-shrink-0"
                  aria-hidden="true"
                />
                <span v-if="!sidebarCollapsed" class="truncate">{{ $t(item.labelKey) }}</span>
              </a>
            </RouterLink>
          </li>
        </ul>
      </div>
    </nav>

    <div :class="['border-t border-border py-2', sidebarCollapsed ? 'px-2' : 'px-3']">
      <button
        type="button"
        class="w-full inline-flex items-center justify-center h-8 rounded text-fg-muted hover:bg-surface-hover hover:text-fg transition"
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
