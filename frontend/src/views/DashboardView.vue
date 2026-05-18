<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Network,
  Tags,
  Router as RouterIcon,
  Server,
  History,
  ArrowUpRight,
  ChevronRight,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import Badge from '@/components/ui/Badge.vue'
import { auditApi, devicesApi, subnetsApi, switchesApi, vlansApi } from '@/api'
import type { AuditLog } from '@/api'
import { useAuth } from '@/composables/useAuth'
import { formatNumber, formatRelativeTime } from '@/utils/formatters'

const { t } = useI18n()
const { isAdmin } = useAuth()

const loading = ref(true)
const counts = ref({ subnets: 0, vlans: 0, switches: 0, devices: 0 })
const recent = ref<AuditLog[]>([])

async function load() {
  loading.value = true
  try {
    const [subnets, vlans, switches, devices, audit] = await Promise.all([
      subnetsApi.list({ page_size: 1 }),
      vlansApi.list({ page_size: 1 }),
      switchesApi.list({ page_size: 1 }),
      devicesApi.list({ page_size: 1 }),
      isAdmin.value
        ? auditApi
            .list({ page_size: 10 })
            .catch(() => ({ items: [] as AuditLog[], total: 0, page: 1, page_size: 10 }))
        : Promise.resolve({ items: [] as AuditLog[], total: 0, page: 1, page_size: 10 }),
    ])
    counts.value = {
      subnets: subnets.total,
      vlans: vlans.total,
      switches: switches.total,
      devices: devices.total,
    }
    recent.value = audit.items
  } finally {
    loading.value = false
  }
}

onMounted(load)

// Each entity tile gets its own colour family so the dashboard reads as a
// real overview rather than four identical indigo cards. The hues stay
// within the iOS system palette (blue / orange / teal / pink-ish purple).
// Each tile's accent classes are kept as full literal strings so Tailwind's
// JIT scanner picks them up. Avoid dynamic concatenation like
// `'hover:' + ring` — Tailwind cannot expand that.
const cards = computed(() => [
  {
    key: 'subnets',
    labelKey: 'nav.subnets',
    icon: Network,
    to: '/subnets',
    value: counts.value.subnets,
    iconClass: 'bg-gradient-to-br from-sky-500 to-indigo-500',
    hoverRingClass: 'hover:ring-sky-500/15',
  },
  {
    key: 'vlans',
    labelKey: 'nav.vlans',
    icon: Tags,
    to: '/vlans',
    value: counts.value.vlans,
    iconClass: 'bg-gradient-to-br from-amber-500 to-orange-500',
    hoverRingClass: 'hover:ring-amber-500/15',
  },
  {
    key: 'switches',
    labelKey: 'nav.switches',
    icon: RouterIcon,
    to: '/switches',
    value: counts.value.switches,
    iconClass: 'bg-gradient-to-br from-emerald-500 to-teal-500',
    hoverRingClass: 'hover:ring-emerald-500/15',
  },
  {
    key: 'devices',
    labelKey: 'nav.devices',
    icon: Server,
    to: '/devices',
    value: counts.value.devices,
    iconClass: 'bg-gradient-to-br from-fuchsia-500 to-purple-500',
    hoverRingClass: 'hover:ring-fuchsia-500/15',
  },
])

const actionTone = {
  create: 'success' as const,
  update: 'primary' as const,
  delete: 'danger' as const,
}
</script>

<template>
  <div class="p-4 sm:p-8 max-w-7xl mx-auto">
    <PageHeader :title="t('nav.dashboard')" :subtitle="t('dashboard.subtitle')" />

    <!-- iOS Today-widget style stat cards. Each one is a full-bleed clickable
         tile with an accented icon disc, a large numeric value, and a hover
         lift via the card-hover shadow. -->
    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
      <RouterLink
        v-for="c in cards"
        :key="c.key"
        :to="c.to"
        :class="[
          'group relative nf-card p-5 transition-all duration-200',
          'hover:shadow-card-hover hover:-translate-y-0.5',
          'ring-1 ring-transparent',
          c.hoverRingClass,
        ]"
      >
        <div class="flex items-start justify-between mb-6">
          <span
            :class="[
              'inline-flex items-center justify-center w-11 h-11 rounded-2xl shadow-sm',
              c.iconClass,
            ]"
          >
            <component
              :is="c.icon"
              class="w-5 h-5 text-white"
              aria-hidden="true"
              :stroke-width="2.25"
            />
          </span>
          <ArrowUpRight
            class="w-4 h-4 text-fg-muted opacity-0 group-hover:opacity-100 transition-opacity"
            aria-hidden="true"
          />
        </div>
        <p class="text-4xl font-semibold tabular-nums text-fg tracking-[-0.02em]">
          <Skeleton v-if="loading" width="3.5rem" height="2rem" rounded="md" />
          <template v-else>{{ formatNumber(c.value) }}</template>
        </p>
        <p class="text-sm text-fg-muted mt-1 font-medium">{{ t(c.labelKey) }}</p>
      </RouterLink>
    </section>

    <section v-if="isAdmin">
      <div class="flex items-center justify-between mb-4 px-1">
        <h2 class="text-xl font-semibold tracking-tight flex items-center gap-2">
          <History class="w-5 h-5 text-fg-muted" :stroke-width="2.25" aria-hidden="true" />
          {{ t('dashboard.recent.title') }}
        </h2>
        <RouterLink
          to="/audit"
          class="inline-flex items-center gap-1 text-sm font-medium text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 transition-colors"
        >
          {{ t('dashboard.recent.viewAll') }}
          <ChevronRight class="w-4 h-4" aria-hidden="true" />
        </RouterLink>
      </div>

      <!-- iOS grouped list — single rounded container, hairline dividers
           between items, no per-row borders. -->
      <div class="nf-card overflow-hidden">
        <ul v-if="loading" class="divide-y divide-border/70 dark:divide-border/40" aria-busy="true">
          <li v-for="i in 5" :key="`sk-recent-${i}`" class="px-5 py-3.5 flex items-center gap-3">
            <Skeleton width="3.5rem" height="1.25rem" rounded="full" />
            <Skeleton width="40%" height="0.75rem" />
            <span class="flex-1" />
            <Skeleton width="4rem" height="0.75rem" />
          </li>
        </ul>
        <div v-else-if="recent.length === 0" class="px-6 py-12 text-center text-sm text-fg-muted">
          {{ t('dashboard.recent.empty') }}
        </div>
        <ul v-else class="divide-y divide-border/70 dark:divide-border/40">
          <li v-for="entry in recent" :key="entry.id" class="px-5 py-3.5 flex items-center gap-3">
            <Badge :tone="actionTone[entry.action]" class="flex-shrink-0">
              {{ t(`audit.actions.${entry.action}`) }}
            </Badge>
            <div class="flex-1 min-w-0 flex items-baseline gap-2">
              <span class="font-mono text-[13px] text-fg">
                {{ entry.entity }}
                <span v-if="entry.entity_id" class="text-fg-muted ml-0.5">
                  #{{ entry.entity_id }}
                </span>
              </span>
              <span class="text-xs text-fg-muted truncate">
                · {{ t('audit.fields.user') }} #{{ entry.user_id ?? '—' }}
              </span>
            </div>
            <span class="text-xs text-fg-muted flex-shrink-0 tabular-nums">
              {{ formatRelativeTime(entry.created_at) }}
            </span>
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>
