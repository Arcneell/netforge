<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Pencil, Sparkles, Download, Grid3x3, Table as TableIcon } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Breadcrumb from '@/components/Breadcrumb.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import VlanBadge from '@/components/VlanBadge.vue'
import IpGrid from '@/components/IpGrid.vue'
import IpEditor from '@/components/editors/IpEditor.vue'
import SubnetEditor from '@/components/editors/SubnetEditor.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import { useStoredRef } from '@/composables/useStoredRef'
import { ipsApi, subnetsApi, vlansApi } from '@/api'
import type { Ip, Subnet, SubnetIpEntry, Vlan } from '@/api'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { formatPercent } from '@/utils/formatters'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { isAdmin } = useAuth()
const { info } = useToast()
const { describe } = useApiErrorMessage()

const subnet = ref<Subnet | null>(null)
const ips = ref<SubnetIpEntry[]>([])
const vlan = ref<Vlan | null>(null)
const loading = ref(true)
// Persist the view mode across reloads — admins flipping between grid and
// table once expect that choice to stick on the same machine.
const view = useStoredRef<'grid' | 'table'>('netforge.subnet.view', 'grid')

const editingSubnet = ref(false)
const editingIpFor = ref<{ ip: Ip | null; address: string | null } | null>(null)

const id = computed(() => Number(route.params.id))

async function load() {
  loading.value = true
  try {
    const [s, list] = await Promise.all([subnetsApi.get(id.value), subnetsApi.ips(id.value)])
    subnet.value = s
    ips.value = list.ips
    vlan.value = s.vlan_id ? await vlansApi.get(s.vlan_id) : null
  } catch (err) {
    void describe(err)
    router.replace('/subnets')
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(id, load)

const stats = computed(() => {
  const total = ips.value.length
  const used = ips.value.filter((i) => i.status !== 'free').length
  const free = total - used
  return { total, used, free, ratio: total ? used / total : 0 }
})

async function suggestNextFree() {
  if (!subnet.value) return
  try {
    const res = await subnetsApi.nextFree(subnet.value.id)
    info(t('subnet.nextFreeFound', { address: res.address }))
    editingIpFor.value = { ip: null, address: res.address }
  } catch (err) {
    info(t('subnet.nextFreeNone'))
    void describe(err)
  }
}

function exportCsv() {
  if (!subnet.value) return
  // Streamed CSV — open in a new tab so the browser handles the download natively.
  window.open(`/api/exports/ips?subnet_id=${subnet.value.id}`, '_blank', 'noopener')
}

async function onIpClick(entry: SubnetIpEntry) {
  if (!isAdmin.value) return
  if (entry.status === 'free') {
    editingIpFor.value = { ip: null, address: entry.address }
    return
  }
  // SubnetIpEntry does not include the IP record id (synthetic-free rows have
  // no DB row at all), so resolve it on demand for occupied addresses.
  try {
    const res = await ipsApi.list({ subnet_id: id.value, q: entry.address, page_size: 1 })
    const hit = res.items.find((i) => i.address === entry.address)
    if (hit) {
      editingIpFor.value = { ip: hit, address: null }
    } else {
      // Stale grid — fall back to create at this address.
      editingIpFor.value = { ip: null, address: entry.address }
    }
  } catch (err) {
    void describe(err)
  }
}

const ipColumns: DataTableColumn[] = [
  { key: 'address', label: t('ip.fields.address'), cellClass: 'font-mono w-40' },
  { key: 'status', label: t('ip.fields.status'), cellClass: 'w-28' },
  { key: 'hostname', label: t('ip.fields.hostname') },
  { key: 'mac', label: t('ip.fields.mac'), cellClass: 'font-mono', hideOnSm: true },
  { key: 'description', label: t('ip.fields.description'), hideOnSm: true },
]

const tableRows = computed(() => ips.value.map((entry) => ({ ...entry, id: entry.address })))

type StatusKey = 'reserved' | 'assigned' | 'dhcp' | 'free'
const statusBadgeTone: Record<StatusKey, 'primary' | 'success' | 'warning' | 'muted'> = {
  assigned: 'primary',
  dhcp: 'success',
  reserved: 'warning',
  free: 'muted',
}
const statusBadgeLabel = computed<Record<StatusKey, string>>(() => ({
  reserved: t('ip.status.reserved'),
  assigned: t('ip.status.assigned'),
  dhcp: t('ip.status.dhcp'),
  free: t('ip.status.free'),
}))
function statusKey(status: string): StatusKey {
  return (status in statusBadgeTone ? status : 'free') as StatusKey
}
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto">
    <div v-if="loading && !subnet" aria-busy="true">
      <div class="mb-3">
        <Skeleton width="14rem" height="0.75rem" />
      </div>
      <div class="mb-6">
        <Skeleton width="14rem" height="1.75rem" rounded="md" />
        <div class="mt-2">
          <Skeleton width="24rem" height="0.875rem" />
        </div>
      </div>
      <section class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div v-for="i in 4" :key="`sk-meta-${i}`" class="nf-card p-4">
          <Skeleton width="6rem" height="0.625rem" />
          <div class="mt-2">
            <Skeleton width="80%" height="0.875rem" />
          </div>
        </div>
      </section>
      <div class="nf-card p-6">
        <Skeleton width="100%" height="14rem" rounded="md" />
      </div>
    </div>

    <template v-else-if="subnet">
      <Breadcrumb
        :items="[
          { label: t('subnet.labelPlural'), to: { name: 'subnets' } },
          { label: subnet.cidr },
        ]"
      />
      <PageHeader :title="subnet.cidr" :subtitle="subnet.description ?? undefined">
        <template #actions>
          <Button variant="secondary" @click="exportCsv">
            <Download class="w-4 h-4" aria-hidden="true" />
            {{ t('subnet.exportCsv') }}
          </Button>
          <Button v-if="isAdmin" variant="secondary" @click="suggestNextFree">
            <Sparkles class="w-4 h-4" aria-hidden="true" />
            {{ t('subnet.nextFree') }}
          </Button>
          <Button v-if="isAdmin" variant="primary" @click="editingSubnet = true">
            <Pencil class="w-4 h-4" aria-hidden="true" />
            {{ t('common.edit') }}
          </Button>
        </template>
      </PageHeader>

      <!-- Metadata + usage card -->
      <section class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div class="nf-card p-4">
          <p class="text-[10px] uppercase tracking-wide text-fg-muted">
            {{ t('subnet.fields.vlan') }}
          </p>
          <div class="mt-1">
            <VlanBadge v-if="vlan" :vlan="vlan" />
            <span v-else class="text-fg-muted text-sm">—</span>
          </div>
        </div>
        <div class="nf-card p-4">
          <p class="text-[10px] uppercase tracking-wide text-fg-muted">
            {{ t('subnet.fields.gateway') }}
          </p>
          <p class="mt-1 font-mono text-sm">{{ subnet.gateway || '—' }}</p>
        </div>
        <div class="nf-card p-4">
          <p class="text-[10px] uppercase tracking-wide text-fg-muted">
            {{ t('subnet.fields.dhcp') }}
          </p>
          <p class="mt-1 text-sm">
            <span v-if="subnet.dhcp_enabled" class="font-mono">
              {{ subnet.dhcp_range_start }} → {{ subnet.dhcp_range_end }}
            </span>
            <span v-else class="text-fg-muted">{{ t('common.no') }}</span>
          </p>
        </div>
        <div class="nf-card p-4">
          <p class="text-[10px] uppercase tracking-wide text-fg-muted">
            {{ t('subnet.fields.usage') }}
          </p>
          <p class="mt-1 text-sm">
            <span class="font-semibold">{{ stats.used }}</span>
            <span class="text-fg-muted">/ {{ stats.total }}</span>
            <span class="text-fg-muted ml-2">({{ formatPercent(stats.ratio, 1) }})</span>
          </p>
          <div class="mt-2 h-1.5 bg-muted rounded overflow-hidden">
            <div
              class="h-full bg-primary-500 transition-all"
              :style="{ width: `${stats.ratio * 100}%` }"
              :aria-valuenow="Math.round(stats.ratio * 100)"
              role="progressbar"
              aria-valuemin="0"
              aria-valuemax="100"
            />
          </div>
        </div>
      </section>

      <!-- View toggle -->
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-lg font-semibold">{{ t('ip.labelPlural') }}</h2>
        <div
          class="inline-flex items-center gap-0.5 p-0.5 rounded-md border border-border bg-surface"
          role="group"
        >
          <button
            type="button"
            :aria-pressed="view === 'grid'"
            :class="[
              'flex items-center gap-1.5 px-2 h-7 rounded text-xs font-medium transition',
              view === 'grid'
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
            ]"
            @click="view = 'grid'"
          >
            <Grid3x3 class="w-3.5 h-3.5" aria-hidden="true" />
            {{ t('subnet.viewGrid') }}
          </button>
          <button
            type="button"
            :aria-pressed="view === 'table'"
            :class="[
              'flex items-center gap-1.5 px-2 h-7 rounded text-xs font-medium transition',
              view === 'table'
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
            ]"
            @click="view = 'table'"
          >
            <TableIcon class="w-3.5 h-3.5" aria-hidden="true" />
            {{ t('subnet.viewTable') }}
          </button>
        </div>
      </div>

      <!-- Grid view -->
      <div v-if="view === 'grid'" class="nf-card p-4">
        <IpGrid :ips="ips" @select="onIpClick" />
      </div>

      <!-- Table view -->
      <DataTable
        v-else
        :columns="ipColumns"
        :rows="tableRows"
        :empty-title="t('ip.labelPlural')"
        clickable
        @row-click="(row) => onIpClick(row)"
      >
        <template #cell-status="{ row }">
          <Badge :tone="statusBadgeTone[statusKey(row.status)]">
            {{ statusBadgeLabel[statusKey(row.status)] }}
          </Badge>
        </template>
        <template #cell-hostname="{ row }">
          <span class="text-fg-muted">{{ row.hostname || '—' }}</span>
        </template>
        <template #cell-mac="{ row }">
          <span class="text-fg-muted">{{ row.mac || '—' }}</span>
        </template>
        <template #cell-description="{ row }">
          <span class="text-fg-muted">{{ row.description || '—' }}</span>
        </template>
      </DataTable>

      <SubnetEditor
        :open="editingSubnet"
        :subnet="subnet"
        @close="editingSubnet = false"
        @saved="load"
      />
      <IpEditor
        v-if="editingIpFor"
        :open="!!editingIpFor"
        :subnet="subnet"
        :ip="editingIpFor.ip"
        :prefilled-address="editingIpFor.address"
        @close="editingIpFor = null"
        @saved="load"
        @deleted="load"
      />
    </template>
  </div>
</template>
