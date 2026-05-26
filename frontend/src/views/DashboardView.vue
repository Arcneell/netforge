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
  AlertTriangle,
  TrendingUp,
  Inbox,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import Badge from '@/components/ui/Badge.vue'
import SubnetFillBar from '@/components/SubnetFillBar.vue'
import { auditApi, devicesApi, subnetsApi, switchesApi, vlansApi } from '@/api'
import type { AuditLog } from '@/api'
import type { SubnetCapacityOverview } from '@/api/endpoints/subnets'
import { useAuth } from '@/composables/useAuth'
import { formatNumber, formatRelativeTime } from '@/utils/formatters'

const { t } = useI18n()
const { isAdmin } = useAuth()

const loading = ref(true)
const counts = ref({ subnets: 0, vlans: 0, switches: 0, devices: 0 })
const recent = ref<AuditLog[]>([])
// Capacity overview drives the "where should I look next?" section.
// Falls back to an empty payload on any error so a flaky `/api/subnets/
// capacity-overview` (e.g. very early deployment with no DB rows yet)
// can't take the whole dashboard down.
const capacity = ref<SubnetCapacityOverview | null>(null)

async function load() {
  loading.value = true
  try {
    const [subnets, vlans, switches, devices, audit, cap] = await Promise.all([
      subnetsApi.list({ page_size: 1 }),
      vlansApi.list({ page_size: 1 }),
      switchesApi.list({ page_size: 1 }),
      devicesApi.list({ page_size: 1 }),
      isAdmin.value
        ? auditApi
            .list({ page_size: 10 })
            .catch(() => ({ items: [] as AuditLog[], total: 0, page: 1, page_size: 10 }))
        : Promise.resolve({ items: [] as AuditLog[], total: 0, page: 1, page_size: 10 }),
      subnetsApi
        .capacityOverview(5)
        .catch(
          () =>
            ({
              fullest: [],
              full: [],
              unused: [],
              total_subnets: 0,
            }) as SubnetCapacityOverview,
        ),
    ])
    counts.value = {
      subnets: subnets.total,
      vlans: vlans.total,
      switches: switches.total,
      devices: devices.total,
    }
    recent.value = audit.items
    capacity.value = cap
  } finally {
    loading.value = false
  }
}

// True when at least one bucket has rows. The whole section hides on
// brand-new deployments (no subnets yet → nothing to rank) so the
// dashboard stays clean for first-time users.
const hasCapacityRows = computed(() => {
  const c = capacity.value
  if (!c) return false
  return c.fullest.length > 0 || c.full.length > 0 || c.unused.length > 0
})

const capacityBuckets = computed(() => [
  {
    key: 'full',
    titleKey: 'dashboard.capacity.full.title',
    helpKey: 'dashboard.capacity.full.help',
    emptyKey: 'dashboard.capacity.full.empty',
    icon: AlertTriangle,
    tone: 'danger' as const,
    items: capacity.value?.full ?? [],
  },
  {
    key: 'fullest',
    titleKey: 'dashboard.capacity.fullest.title',
    helpKey: 'dashboard.capacity.fullest.help',
    emptyKey: 'dashboard.capacity.fullest.empty',
    icon: TrendingUp,
    tone: 'warning' as const,
    items: capacity.value?.fullest ?? [],
  },
  {
    key: 'unused',
    titleKey: 'dashboard.capacity.unused.title',
    helpKey: 'dashboard.capacity.unused.help',
    emptyKey: 'dashboard.capacity.unused.empty',
    icon: Inbox,
    tone: 'muted' as const,
    items: capacity.value?.unused ?? [],
  },
])

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

    <!-- Capacity hot-spots. Three columns of "things worth looking at":
         at-capacity / nearly-full / unused. Each row is a clickable
         RouterLink to the subnet detail. The whole section hides on
         empty deployments so a fresh install doesn't show three empty
         placeholders. -->
    <section v-if="loading || hasCapacityRows" class="mb-10">
      <div class="flex items-center justify-between mb-4 px-1">
        <h2 class="text-xl font-semibold tracking-tight flex items-center gap-2">
          <TrendingUp
            class="w-5 h-5 text-fg-muted"
            :stroke-width="2.25"
            aria-hidden="true"
          />
          {{ t('dashboard.capacity.title') }}
        </h2>
        <span v-if="capacity" class="text-xs text-fg-muted tabular-nums">
          {{ t('dashboard.capacity.subtitle', { n: capacity.total_subnets }) }}
        </span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div
          v-for="bucket in capacityBuckets"
          :key="bucket.key"
          class="nf-card overflow-hidden flex flex-col"
        >
          <header class="px-4 py-3 border-b border-border/60 flex items-start gap-2">
            <component
              :is="bucket.icon"
              :class="[
                'w-4 h-4 mt-0.5 flex-shrink-0',
                bucket.tone === 'danger'
                  ? 'text-danger'
                  : bucket.tone === 'warning'
                    ? 'text-warning'
                    : 'text-fg-muted',
              ]"
              aria-hidden="true"
            />
            <div class="min-w-0">
              <p class="text-sm font-semibold text-fg">{{ t(bucket.titleKey) }}</p>
              <p class="text-xs text-fg-muted mt-0.5">{{ t(bucket.helpKey) }}</p>
            </div>
          </header>

          <ul v-if="loading" class="divide-y divide-border/40" aria-busy="true">
            <li v-for="i in 3" :key="`sk-cap-${bucket.key}-${i}`" class="px-4 py-2.5">
              <Skeleton width="70%" height="0.75rem" />
              <div class="mt-1.5">
                <Skeleton width="40%" height="0.625rem" />
              </div>
            </li>
          </ul>
          <p
            v-else-if="bucket.items.length === 0"
            class="px-4 py-6 text-xs text-fg-muted text-center"
          >
            {{ t(bucket.emptyKey) }}
          </p>
          <ul v-else class="divide-y divide-border/40">
            <li v-for="entry in bucket.items" :key="entry.id">
              <RouterLink
                :to="`/subnets/${entry.id}`"
                class="block px-4 py-2.5 hover:bg-surface-hover transition-colors"
              >
                <div class="flex items-center gap-2 min-w-0">
                  <span class="font-mono text-sm font-medium text-fg truncate">
                    {{ entry.cidr }}
                  </span>
                  <span class="text-xs text-fg-muted tabular-nums ml-auto flex-shrink-0">
                    {{ entry.used_pct }}%
                  </span>
                </div>
                <div class="mt-1.5 flex items-center gap-2">
                  <SubnetFillBar
                    :used="entry.used"
                    :usable="entry.usable"
                    bar-class="flex-1"
                  />
                </div>
                <p
                  v-if="entry.description"
                  class="mt-1 text-xs text-fg-muted truncate"
                >
                  {{ entry.description }}
                </p>
              </RouterLink>
            </li>
          </ul>
        </div>
      </div>
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
