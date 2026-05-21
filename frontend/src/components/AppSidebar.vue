<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { aiApi, type AIStatus } from '@/api'
import {
  ClipboardList,
  Diff,
  LayoutDashboard,
  Lightbulb,
  MessageCircle,
  Network,
  Tags,
  Router as RouterIcon,
  Server,
  Share2,
  Upload,
  History,
  Settings,
  X,
} from 'lucide-vue-next'
import { storeToRefs } from 'pinia'
import { useUiStore } from '@/stores/ui'
import { useAuth } from '@/composables/useAuth'
import BrandMark from '@/components/BrandMark.vue'

interface NavItem {
  to: string
  icon: typeof LayoutDashboard
  labelKey: string
  /** Hide this item if the matching AI sub-feature is disabled (per
   *  /api/ai/status). Used to keep the "Drafted actions" entry out of the
   *  sidebar when the operator has opted out of NL-to-action. */
  requiresAiFeature?: 'drafts'
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
      { to: '/insights', icon: Lightbulb, labelKey: 'nav.insights' },
      { to: '/ask', icon: MessageCircle, labelKey: 'nav.ask' },
      {
        to: '/drafts',
        icon: ClipboardList,
        labelKey: 'nav.drafts',
        requiresAiFeature: 'drafts',
      },
      { to: '/import', icon: Upload, labelKey: 'nav.import' },
      { to: '/audit', icon: History, labelKey: 'nav.audit' },
      { to: '/snapshots/compare', icon: Diff, labelKey: 'nav.snapshots' },
      { to: '/settings', icon: Settings, labelKey: 'nav.settings' },
    ],
  },
]

const ui = useUiStore()
const { sidebarCollapsed, mobileNavOpen } = storeToRefs(ui)
const { isAdmin } = useAuth()
const route = useRoute()

// Lazily fetch AI status for the admin sidebar — the call is cheap (200,
// public to authed users) and only triggered for admins because the items
// gated by it live in the admin-only section. Falls back to "everything
// enabled" on error so an outage of the AI endpoint can't lock the sidebar.
const aiStatus = ref<AIStatus | null>(null)
onMounted(async () => {
  if (!isAdmin.value) return
  try {
    aiStatus.value = await aiApi.status()
  } catch {
    aiStatus.value = null
  }
})

function itemAllowed(item: NavItem): boolean {
  if (item.requiresAiFeature === 'drafts') {
    // Hide until we know better; once status loaded, gate on the flag.
    if (!aiStatus.value) return false
    return aiStatus.value.drafts_enabled
  }
  return true
}

const visibleSections = computed(() => {
  return sections
    .filter((s) => !s.adminOnly || isAdmin.value)
    .map((s) => ({ ...s, items: s.items.filter(itemAllowed) }))
    .filter((s) => s.items.length > 0)
})

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
      class="md:hidden fixed inset-0 bg-zinc-950/40 z-30"
      aria-hidden="true"
      @click="ui.setMobileNavOpen(false)"
    />
  </Transition>

  <aside
    :class="[
      'flex flex-col bg-bg border-r border-border/60 dark:border-border/30 transition-transform duration-200 md:transition-[width]',
      // Mobile drawer uses the elevated surface for the iOS sheet feel.
      'md:bg-bg bg-surface',
      'fixed md:static inset-y-0 left-0 z-40 w-64 md:w-auto',
      sidebarCollapsed ? 'md:w-16' : 'md:w-64',
      mobileNavOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0',
    ]"
    aria-label="Primary"
  >
    <div
      :class="[
        'h-14 flex items-center',
        sidebarCollapsed ? 'md:justify-center md:px-2 px-4' : 'px-4',
      ]"
    >
      <BrandMark :show-wordmark="!sidebarCollapsed || mobileNavOpen" :size="26" />
      <!-- Close button only on mobile -->
      <button
        type="button"
        class="md:hidden ml-auto inline-flex items-center justify-center w-8 h-8 rounded text-fg-muted hover:bg-surface-hover hover:text-fg transition"
        aria-label="Close navigation"
        @click="ui.setMobileNavOpen(false)"
      >
        <X class="w-4 h-4" aria-hidden="true" />
      </button>
    </div>

    <nav class="flex-1 overflow-y-auto py-4 px-3">
      <div v-for="(section, sIdx) in visibleSections" :key="sIdx" :class="[sIdx > 0 ? 'mt-6' : '']">
        <!--
          Section captions live on the left margin in expanded mode. Collapsed
          mode hides them (the user only sees icons, captions would just be
          tooltips with no anchor), but we keep a thin divider line so the
          three groups stay visually distinct even at 64 px wide.
        -->
        <!-- Caption: always rendered. On desktop-collapsed it hides and the
             <hr> below it shows instead so the three sections stay visually
             distinct at 64 px wide. -->
        <p
          v-if="section.titleKey"
          class="px-3 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-fg-muted"
          :class="sidebarCollapsed ? 'md:hidden' : ''"
        >
          {{ $t(section.titleKey) }}
        </p>
        <hr
          v-if="section.titleKey && sidebarCollapsed"
          class="hidden md:block mx-3 mb-1.5 border-border"
        />
        <ul class="space-y-0.5">
          <li v-for="item in section.items" :key="item.to">
            <RouterLink v-slot="{ href, navigate, isActive, isExactActive }" :to="item.to" custom>
              <a
                :href="href"
                :class="[
                  'group flex items-center gap-3 rounded-lg text-sm font-medium transition-colors',
                  sidebarCollapsed ? 'px-3 py-2.5 md:justify-center md:px-2' : 'px-3 py-2.5',
                  (item.to === '/' ? isExactActive : isActive)
                    ? 'bg-surface text-fg shadow-card'
                    : 'text-fg-muted hover:bg-surface/60 hover:text-fg',
                ]"
                :title="sidebarCollapsed ? $t(item.labelKey) : undefined"
                :aria-label="$t(item.labelKey)"
                :aria-current="(item.to === '/' ? isExactActive : isActive) ? 'page' : undefined"
                @click="navigate"
              >
                <component
                  :is="item.icon"
                  :class="[
                    'w-[18px] h-[18px] flex-shrink-0 transition-colors',
                    (item.to === '/' ? isExactActive : isActive)
                      ? 'text-primary-600 dark:text-primary-400'
                      : '',
                  ]"
                  aria-hidden="true"
                />
                <span class="truncate" :class="sidebarCollapsed ? 'md:hidden' : ''">
                  {{ $t(item.labelKey) }}
                </span>
              </a>
            </RouterLink>
          </li>
        </ul>
      </div>
    </nav>

    <!-- Desktop only: collapse / expand toggle. On mobile the user closes the
         drawer via the X in the header or the backdrop tap. -->
    <div :class="['hidden md:block py-2', sidebarCollapsed ? 'px-2' : 'px-3']">
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
