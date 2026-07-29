<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Network, Tags, Router as RouterIcon, Server, ArrowRight } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import AddressSpaceBand from '@/components/AddressSpaceBand.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import Badge from '@/components/ui/Badge.vue'
import SubnetFillBar from '@/components/SubnetFillBar.vue'
import { auditApi, devicesApi, subnetsApi, switchesApi, vlansApi } from '@/api'
import type { AuditLog, Subnet } from '@/api'
import type { SubnetCapacityOverview } from '@/api/endpoints/subnets'
import { useAuth } from '@/composables/useAuth'
import { formatNumber, formatRelativeTime } from '@/utils/formatters'

const { t } = useI18n()
const { isAdmin } = useAuth()

const loading = ref(true)
const counts = ref({ subnets: 0, vlans: 0, switches: 0, devices: 0 })
const recent = ref<AuditLog[]>([])
// Feeds the address band. 200 is the API's page ceiling; past that the band says
// so rather than quietly drawing a partial picture.
const bandSubnets = ref<Subnet[]>([])
// Capacity overview drives the "where should I look next?" section.
// Falls back to an empty payload on any error so a flaky `/api/subnets/
// capacity-overview` (e.g. very early deployment with no DB rows yet)
// can't take the whole dashboard down.
const capacity = ref<SubnetCapacityOverview | null>(null)

async function load() {
  loading.value = true
  try {
    const [subnets, vlans, switches, devices, audit, cap] = await Promise.all([
      // One request serves both the band and the subnet count — `total` comes
      // back on the same envelope, so there's no separate count call.
      subnetsApi.list({ page_size: 200 }),
      vlansApi.list({ page_size: 1 }),
      switchesApi.list({ page_size: 1 }),
      devicesApi.list({ page_size: 1 }),
      isAdmin.value
        ? auditApi
            .list({ page_size: 8 })
            .catch(() => ({ items: [] as AuditLog[], total: 0, page: 1, page_size: 8 }))
        : Promise.resolve({ items: [] as AuditLog[], total: 0, page: 1, page_size: 8 }),
      subnetsApi.capacityOverview(5).catch(
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
    bandSubnets.value = subnets.items
    recent.value = audit.items
    capacity.value = cap
  } finally {
    loading.value = false
  }
}

// Show the panel whenever there's any subnet on file. Gating on
// "at least one bucket has rows" hid the section for healthy
// mid-fill deployments where every subnet sits in the 1–79 % range,
// which is the exact state most operators run in (Codex P2 on #79).
// The empty-bucket placeholders are already the right message there.
const hasCapacity = computed(() => (capacity.value?.total_subnets ?? 0) > 0)

const capacityBuckets = computed(() => [
  {
    key: 'full',
    titleKey: 'dashboard.capacity.full.title',
    helpKey: 'dashboard.capacity.full.help',
    emptyKey: 'dashboard.capacity.full.empty',
    tone: 'danger' as const,
    // The count is the headline of each bucket, so it carries the bucket's
    // status colour directly rather than sitting next to a coloured chip.
    figureClass: 'text-danger',
    items: capacity.value?.full ?? [],
  },
  {
    key: 'fullest',
    titleKey: 'dashboard.capacity.fullest.title',
    helpKey: 'dashboard.capacity.fullest.help',
    emptyKey: 'dashboard.capacity.fullest.empty',
    tone: 'warning' as const,
    figureClass: 'text-warning',
    items: capacity.value?.fullest ?? [],
  },
  {
    key: 'unused',
    titleKey: 'dashboard.capacity.unused.title',
    helpKey: 'dashboard.capacity.unused.help',
    emptyKey: 'dashboard.capacity.unused.empty',
    tone: 'neutral' as const,
    figureClass: 'text-fg-muted',
    items: capacity.value?.unused ?? [],
  },
])

onMounted(load)

const cards = computed(() => [
  {
    key: 'subnets',
    labelKey: 'nav.subnets',
    icon: Network,
    to: '/subnets',
    value: counts.value.subnets,
  },
  { key: 'vlans', labelKey: 'nav.vlans', icon: Tags, to: '/vlans', value: counts.value.vlans },
  {
    key: 'switches',
    labelKey: 'nav.switches',
    icon: RouterIcon,
    to: '/switches',
    value: counts.value.switches,
  },
  {
    key: 'devices',
    labelKey: 'nav.devices',
    icon: Server,
    to: '/devices',
    value: counts.value.devices,
  },
])

const actionTone = {
  create: 'success' as const,
  update: 'primary' as const,
  delete: 'danger' as const,
}
</script>

<template>
  <div class="px-4 py-7 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="t('nav.dashboard')" :subtitle="t('dashboard.subtitle')" />

    <!-- The thesis: the address space itself, at real scale.

         `nf-no-enter` opts it out of the page stagger — it owns its own
         entrance, sweeping its bars left to right, and the sections below rise
         underneath while that plays. Two motions, one sequence. -->
    <AddressSpaceBand
      :subnets="bandSubnets"
      :loading="loading"
      :total="counts.subnets"
      class="nf-no-enter mb-8"
    />

    <!-- Inventory. One strip of four figures on a hairline grid — the gap-px
         trick means the same markup gives a clean 2×2 on mobile and a 1×4 on
         desktop with no per-breakpoint border juggling. -->
    <section
      class="grid grid-cols-2 lg:grid-cols-4 gap-px bg-border border border-border rounded-lg overflow-hidden shadow-xs mb-8"
    >
      <RouterLink
        v-for="c in cards"
        :key="c.key"
        :to="c.to"
        class="group nf-interactive bg-surface px-5 py-4 flex items-start gap-3"
      >
        <div class="min-w-0 flex-1">
          <p class="nf-legend">{{ t(c.labelKey) }}</p>
          <p class="nf-figure text-3xl mt-1.5">
            <Skeleton v-if="loading" width="3rem" height="1.5rem" rounded="md" />
            <template v-else>{{ formatNumber(c.value) }}</template>
          </p>
        </div>
        <component
          :is="c.icon"
          class="w-4 h-4 flex-shrink-0 text-fg-subtle group-hover:text-fg-muted transition-colors duration-150 ease-panel"
          :stroke-width="1.75"
          aria-hidden="true"
        />
      </RouterLink>
    </section>

    <!-- Capacity hot-spots: at capacity / filling up / unused. -->
    <section v-if="loading || hasCapacity" class="mb-8">
      <div class="flex items-baseline justify-between gap-x-4 gap-y-1 mb-3 flex-wrap">
        <h2 class="nf-section-title">{{ t('dashboard.capacity.title') }}</h2>
        <span v-if="capacity" class="nf-legend">
          {{ t('dashboard.capacity.subtitle', { n: capacity.total_subnets }) }}
        </span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div
          v-for="bucket in capacityBuckets"
          :key="bucket.key"
          class="nf-card overflow-hidden flex flex-col"
        >
          <!-- min-height keeps the three headers the same height so the lists
               below them start on the same line. -->
          <header class="px-5 pt-4 pb-3 min-h-[6.5rem]">
            <p class="nf-legend">{{ t(bucket.titleKey) }}</p>
            <p class="nf-figure text-2xl mt-1" :class="bucket.figureClass">
              <Skeleton v-if="loading" width="1.5rem" height="1.25rem" rounded="md" />
              <template v-else>{{ bucket.items.length }}</template>
            </p>
            <p class="text-xs text-fg-muted mt-1.5">{{ t(bucket.helpKey) }}</p>
          </header>

          <ul v-if="loading" class="border-t border-border divide-y divide-border" aria-busy="true">
            <li v-for="i in 3" :key="`sk-cap-${bucket.key}-${i}`" class="px-5 py-3">
              <Skeleton width="60%" height="0.75rem" />
              <div class="mt-2">
                <Skeleton width="35%" height="0.625rem" />
              </div>
            </li>
          </ul>
          <p
            v-else-if="bucket.items.length === 0"
            class="px-5 pb-6 pt-2 text-sm text-fg-subtle flex-1"
          >
            {{ t(bucket.emptyKey) }}
          </p>
          <ul v-else class="border-t border-border divide-y divide-border">
            <li v-for="entry in bucket.items" :key="entry.id">
              <RouterLink
                :to="`/subnets/${entry.id}`"
                class="block px-5 py-3 hover:bg-surface-hover transition-colors duration-150 ease-panel"
              >
                <div class="flex items-center justify-between gap-3">
                  <span class="font-mono text-sm text-fg truncate">{{ entry.cidr }}</span>
                  <SubnetFillBar
                    :used="entry.used"
                    :usable="entry.usable"
                    bar-class="w-16"
                    class="flex-shrink-0"
                  />
                </div>
                <p v-if="entry.description" class="text-xs text-fg-muted truncate mt-1">
                  {{ entry.description }}
                </p>
              </RouterLink>
            </li>
          </ul>
        </div>
      </div>
    </section>

    <section v-if="isAdmin">
      <div class="flex items-baseline justify-between gap-4 mb-3">
        <h2 class="nf-section-title">{{ t('dashboard.recent.title') }}</h2>
        <RouterLink
          to="/data/audit"
          class="inline-flex items-center gap-1 text-sm font-medium nf-link no-underline hover:no-underline"
        >
          {{ t('dashboard.recent.viewAll') }}
          <ArrowRight class="w-3.5 h-3.5" aria-hidden="true" />
        </RouterLink>
      </div>

      <div class="nf-card overflow-hidden">
        <ul v-if="loading" class="divide-y divide-border" aria-busy="true">
          <li v-for="i in 5" :key="`sk-recent-${i}`" class="px-5 py-3.5 flex items-center gap-3">
            <Skeleton width="4rem" height="1.25rem" rounded="md" />
            <Skeleton width="35%" height="0.75rem" />
            <span class="flex-1" />
            <Skeleton width="4rem" height="0.75rem" />
          </li>
        </ul>
        <div v-else-if="recent.length === 0" class="px-6 py-12 text-center text-base text-fg-muted">
          {{ t('dashboard.recent.empty') }}
        </div>
        <ul v-else class="divide-y divide-border">
          <li v-for="entry in recent" :key="entry.id" class="px-5 py-3.5 flex items-center gap-3">
            <Badge :tone="actionTone[entry.action]" class="flex-shrink-0">
              {{ t(`audit.actions.${entry.action}`) }}
            </Badge>
            <span class="text-base text-fg truncate">
              {{ entry.entity }}
              <span v-if="entry.entity_id" class="text-fg-subtle">#{{ entry.entity_id }}</span>
            </span>
            <span class="ml-auto text-xs text-fg-muted flex-shrink-0 tabular-nums">
              {{ formatRelativeTime(entry.created_at) }}
            </span>
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>
