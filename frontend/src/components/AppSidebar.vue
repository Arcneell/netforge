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
} from '@lucide/vue'
import { storeToRefs } from 'pinia'
import { useUiStore } from '@/stores/ui'
import { useAuth } from '@/composables/useAuth'
import BrandMark from '@/components/BrandMark.vue'

interface NavItem {
  to: string
  icon: typeof LayoutGrid
  labelKey: string
  adminOnly?: boolean
  /** Small trailing tag, e.g. to flag a section that is being rebuilt. */
  badgeKey?: string
}

interface NavGroup {
  /** Legend above the group. Names what kind of thing lives in it. */
  legendKey: string
  items: NavItem[]
}

// Two groups, because there are genuinely two kinds of entry here: things the
// network *is* (records you look up all day) and tools that act on them. The
// legends aren't decoration — they tell you which half you're in before you
// read a single label. Six inventory entries stay one click away; everything
// administrative collapses into the three workspaces, which carry their own
// tabs.
const groups: NavGroup[] = [
  {
    legendKey: 'nav.sections.network',
    items: [
      { to: '/', icon: LayoutGrid, labelKey: 'nav.dashboard' },
      { to: '/subnets', icon: Network, labelKey: 'nav.subnets' },
      { to: '/vlans', icon: Tags, labelKey: 'nav.vlans' },
      { to: '/switches', icon: RouterIcon, labelKey: 'nav.switches' },
      { to: '/devices', icon: Server, labelKey: 'nav.devices' },
      { to: '/topology', icon: Share2, labelKey: 'nav.topology' },
    ],
  },
  {
    legendKey: 'nav.sections.administration',
    items: [
      { to: '/assistant', icon: Sparkles, labelKey: 'nav.assistant', adminOnly: true },
      { to: '/data', icon: Database, labelKey: 'nav.data', adminOnly: true },
      { to: '/settings', icon: Settings, labelKey: 'nav.settings', adminOnly: true },
    ],
  },
]

const ui = useUiStore()
const { sidebarCollapsed, mobileNavOpen } = storeToRefs(ui)
const { isAdmin } = useAuth()
const route = useRoute()

const visibleGroups = computed(() =>
  groups
    .map((g) => ({ ...g, items: g.items.filter((i) => !i.adminOnly || isAdmin.value) }))
    .filter((g) => g.items.length > 0),
)

// Labels are hidden on the desktop rail when collapsed, but the mobile drawer
// is always full width — it slides in over the content and has room.
const showLabels = computed(() => !sidebarCollapsed.value || mobileNavOpen.value)

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
      class="md:hidden fixed inset-0 bg-plate/70 z-30"
      aria-hidden="true"
      @click="ui.setMobileNavOpen(false)"
    />
  </Transition>

  <!-- The rail. An engraved plate bolted to the left edge of the cabinet: dark
       in both themes, square, and the only large dark mass in the light theme.
       Everything it holds is a label on hardware. -->
  <aside
    :class="[
      // 160ms on the width: the labels are toggled with `v-if` rather than
      // faded, so a slower collapse just gives the eye more time to notice
      // them pop. Snapping through it reads as one mechanical movement.
      'flex flex-col bg-plate text-plate-fg transition-transform duration-200 ease-panel md:transition-[width] md:duration-[160ms]',
      'fixed md:static inset-y-0 left-0 z-40 w-64 md:w-auto',
      sidebarCollapsed ? 'md:w-14' : 'md:w-60',
      mobileNavOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0',
    ]"
    aria-label="Primary"
  >
    <div
      :class="[
        'h-[3.25rem] flex items-center flex-shrink-0',
        sidebarCollapsed && !mobileNavOpen ? 'md:justify-center md:px-0 px-4' : 'px-4',
      ]"
    >
      <BrandMark :show-wordmark="showLabels" :size="22" on-plate />
      <button
        type="button"
        class="md:hidden ml-auto inline-flex items-center justify-center w-8 h-8 rounded-md text-plate-fg-muted hover:bg-plate-raised hover:text-plate-fg transition-colors duration-150 ease-panel"
        aria-label="Close navigation"
        @click="ui.setMobileNavOpen(false)"
      >
        <X class="w-4 h-4" aria-hidden="true" />
      </button>
    </div>

    <nav class="flex-1 overflow-y-auto overflow-x-hidden pb-4">
      <div v-for="(group, gi) in visibleGroups" :key="group.legendKey">
        <!-- Legend, or a bare hairline once the rail is collapsed and there is
             no room to name the group. The first group needs neither: the
             brand above it already closes off the top. -->
        <p
          v-if="showLabels"
          class="nf-legend text-plate-fg-muted px-4 pt-5 pb-2"
          :class="gi === 0 ? 'md:pt-3' : ''"
        >
          {{ $t(group.legendKey) }}
        </p>
        <hr
          v-else-if="gi > 0"
          class="hidden md:block border-plate-border mx-3 my-3"
          aria-hidden="true"
        />

        <ul>
          <li v-for="item in group.items" :key="item.to">
            <RouterLink v-slot="{ href, navigate, isActive, isExactActive }" :to="item.to" custom>
              <a
                :href="href"
                :class="[
                  'relative group flex items-center gap-3 h-9 text-base',
                  'transition-colors duration-150 ease-panel',
                  showLabels ? 'px-4' : 'px-4 md:justify-center md:px-0',
                  (item.to === '/' ? isExactActive : isActive)
                    ? 'bg-plate-raised text-plate-fg font-medium'
                    : 'text-plate-fg-muted font-normal hover:bg-plate-raised hover:text-plate-fg',
                ]"
                :title="showLabels ? undefined : $t(item.labelKey)"
                :aria-current="(item.to === '/' ? isExactActive : isActive) ? 'page' : undefined"
                @click="navigate"
              >
                <!-- The lit rail contact. Flush to the plate's left edge, 2px,
                     accent — the whole "you are here" signal, no pill, no tint
                     bleeding across the row. -->
                <span
                  v-if="item.to === '/' ? isExactActive : isActive"
                  class="absolute left-0 top-0 bottom-0 w-[2px] bg-primary-400"
                  aria-hidden="true"
                />
                <component
                  :is="item.icon"
                  class="w-[17px] h-[17px] flex-shrink-0"
                  :stroke-width="1.75"
                  aria-hidden="true"
                />
                <span v-if="showLabels" class="truncate">{{ $t(item.labelKey) }}</span>
                <span
                  v-if="item.badgeKey && showLabels"
                  class="ml-auto nf-legend text-[0.625rem] text-warning"
                >
                  {{ $t(item.badgeKey) }}
                </span>
              </a>
            </RouterLink>
          </li>
        </ul>
      </div>
    </nav>

    <!-- Desktop only: collapse / expand toggle. On mobile the user closes the
         drawer via the X in the header or the backdrop tap. -->
    <div class="hidden md:block border-t border-plate-border">
      <button
        type="button"
        class="w-full inline-flex items-center justify-center h-9 text-plate-fg-muted hover:bg-plate-raised hover:text-plate-fg transition-colors duration-150 ease-panel"
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
