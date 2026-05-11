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
  adminOnly?: boolean
}

const items: NavItem[] = [
  { to: '/', icon: LayoutDashboard, labelKey: 'nav.dashboard' },
  { to: '/subnets', icon: Network, labelKey: 'nav.subnets' },
  { to: '/vlans', icon: Tags, labelKey: 'nav.vlans' },
  { to: '/switches', icon: RouterIcon, labelKey: 'nav.switches' },
  { to: '/devices', icon: Server, labelKey: 'nav.devices' },
  { to: '/topology', icon: Share2, labelKey: 'nav.topology' },
  { to: '/import', icon: Upload, labelKey: 'nav.import', adminOnly: true },
  { to: '/audit', icon: History, labelKey: 'nav.audit', adminOnly: true },
  { to: '/settings', icon: Settings, labelKey: 'nav.settings', adminOnly: true },
]

const ui = useUiStore()
const { sidebarCollapsed } = storeToRefs(ui)
const { isAdmin } = useAuth()

const visible = computed(() => items.filter((i) => !i.adminOnly || isAdmin.value))
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
      <ul class="space-y-0.5">
        <li v-for="item in visible" :key="item.to">
          <RouterLink v-slot="{ href, navigate, isActive, isExactActive }" :to="item.to" custom>
            <a
              :href="href"
              :class="[
                'group flex items-center gap-3 rounded-md text-sm font-medium transition',
                sidebarCollapsed ? 'justify-center px-2 py-2' : 'px-3 py-2',
                (item.to === '/' ? isExactActive : isActive)
                  ? 'bg-primary-50 text-primary-700 dark:bg-primary-100/20 dark:text-primary-50'
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
