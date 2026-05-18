<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Network, Tags, Router as RouterIcon, Server, History, ArrowRight } from 'lucide-vue-next'
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

// All counts come from the total field of paginated list endpoints — page_size=1
// keeps the payload minimal. Audit-log access is admin-only, so guard the call.
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
  <div class="p-4 sm:p-6 max-w-7xl mx-auto">
    <PageHeader :title="t('nav.dashboard')" :subtitle="t('dashboard.subtitle')" />

    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <RouterLink
        v-for="c in cards"
        :key="c.key"
        :to="c.to"
        class="nf-card p-5 hover:border-primary-300 hover:bg-surface-hover transition group"
      >
        <div class="flex items-center justify-between mb-3">
          <span
            class="inline-flex items-center justify-center w-9 h-9 rounded-md bg-primary-50 text-primary-600 dark:bg-primary-900/30 dark:text-primary-300"
          >
            <component :is="c.icon" class="w-4 h-4" aria-hidden="true" />
          </span>
          <ArrowRight
            class="w-4 h-4 text-fg-muted opacity-0 group-hover:opacity-100 transition"
            aria-hidden="true"
          />
        </div>
        <p class="text-3xl font-semibold tabular-nums text-fg">
          <Skeleton v-if="loading" width="3rem" height="1.75rem" rounded="md" />
          <template v-else>{{ formatNumber(c.value) }}</template>
        </p>
        <p class="text-xs text-fg-muted mt-0.5">{{ t(c.labelKey) }}</p>
      </RouterLink>
    </section>

    <section v-if="isAdmin">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold flex items-center gap-2">
          <History class="w-4 h-4" aria-hidden="true" />
          {{ t('dashboard.recent.title') }}
        </h2>
        <RouterLink to="/audit" class="text-xs nf-link">
          {{ t('dashboard.recent.viewAll') }}
        </RouterLink>
      </div>
      <div class="nf-card">
        <ul v-if="loading" class="divide-y divide-border" aria-busy="true">
          <li v-for="i in 5" :key="`sk-recent-${i}`" class="px-4 py-2.5 flex items-center gap-3">
            <Skeleton width="3.5rem" height="1.25rem" rounded="md" />
            <Skeleton width="40%" height="0.75rem" />
            <span class="flex-1" />
            <Skeleton width="4rem" height="0.75rem" />
          </li>
        </ul>
        <ul v-else-if="recent.length === 0" class="p-10 text-center text-sm text-fg-muted">
          {{
            t('dashboard.recent.empty')
          }}
        </ul>
        <ul v-else class="divide-y divide-border">
          <li v-for="entry in recent" :key="entry.id" class="px-4 py-2.5 flex items-center gap-3">
            <Badge :tone="actionTone[entry.action]" class="flex-shrink-0">
              {{ t(`audit.actions.${entry.action}`) }}
            </Badge>
            <div class="flex-1 min-w-0 flex items-baseline gap-2">
              <span class="font-mono text-xs text-fg">
                {{ entry.entity }}
                <span v-if="entry.entity_id">#{{ entry.entity_id }}</span>
              </span>
              <span class="text-xs text-fg-muted truncate">
                · {{ t('audit.fields.user') }} #{{ entry.user_id ?? '—' }}
              </span>
            </div>
            <span class="text-xs text-fg-muted flex-shrink-0">
              {{ formatRelativeTime(entry.created_at) }}
            </span>
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>
