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
import { ApiError, ipsApi, subnetsApi, vlansApi } from '@/api'
import type { Ip, Subnet, SubnetIpEntry, SubnetUtilization, Vlan } from '@/api'

// `ip_id` was added to SubnetIpEntry in PR perf/ipam-indexes-and-group-by
// so the editor can be opened with one fetch instead of two. The optional
// chain keeps the code working against older API responses (the field is
// nullable for synthetic free/dhcp rows anyway).
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
const utilization = ref<SubnetUtilization | null>(null)
const loading = ref(true)
// Persist the view mode across reloads — admins flipping between grid and
// table once expect that choice to stick on the same machine.
const view = useStoredRef<'grid' | 'table'>('netforge.subnet.view', 'grid')

const editingSubnet = ref(false)
const editingIpFor = ref<{ ip: Ip | null; address: string | null } | null>(null)
// True when `/ips` refused to enumerate the address space because the
// subnet is bigger than the server-side cap (`SUBNET_TOO_LARGE`). The
// utilisation card still renders — we just hide the grid and surface
// an explicit explanation so the operator doesn't read "empty grid" as
// "empty subnet".
const tooLarge = ref(false)

const id = computed(() => Number(route.params.id))

async function load() {
  loading.value = true
  tooLarge.value = false
  try {
    // Fetch the subnet + utilisation in parallel — the utilisation endpoint
    // works on any prefix length (two SELECTs, no address-space scan), so
    // we always have the headline fill rate even for /20 and larger blocks.
    // The IP enumeration (`/ips`) is bounded server-side; we let it fail
    // soft on huge subnets so the page still renders with the utilisation
    // bar and an explicit "too large" banner instead of a confusing empty
    // grid.
    const [s, util] = await Promise.all([
      subnetsApi.get(id.value),
      subnetsApi.utilization(id.value),
    ])
    subnet.value = s
    utilization.value = util
    vlan.value = s.vlan_id ? await vlansApi.get(s.vlan_id) : null
    try {
      const list = await subnetsApi.ips(id.value)
      ips.value = list.ips
    } catch (err) {
      // Only swallow the size cap — every other failure (network, auth,
      // 500) must surface to the user so an empty grid isn't mistaken for
      // a real empty subnet. SUBNET_TOO_LARGE is the deliberate server-side
      // refusal to materialise the whole address space for prefixes wider
      // than /20.
      if (err instanceof ApiError && err.code === 'SUBNET_TOO_LARGE') {
        ips.value = []
        tooLarge.value = true
      } else {
        throw err
      }
    }
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
  // Prefer the cheap server-side utilisation when available — it works on
  // any prefix length and matches the integrity check's accounting. Falls
  // back to the in-memory IPs list for the loading window before util
  // arrives (and as a last resort if the endpoint is unreachable).
  if (utilization.value) {
    const total = utilization.value.usable
    const used = total - utilization.value.free
    return {
      total,
      used,
      free: utilization.value.free,
      ratio: total ? used / total : 0,
    }
  }
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
    // Admins flow straight into the IP editor with the suggestion
    // prefilled — one less click to actually assign. Viewers get the
    // toast and nothing else; the backend endpoint is open to them too,
    // but they have no write capability to follow up with.
    if (isAdmin.value) {
      editingIpFor.value = { ip: null, address: res.address }
    }
  } catch (err) {
    if (err instanceof ApiError && err.code === 'SUBNET_FULL') {
      info(t('subnet.nextFreeNone'))
      return
    }
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
  // The entry carries `ip_id` when the row exists in the DB — open the
  // editor directly without a second round-trip. Synthetic "dhcp" rows
  // for addresses inside a DHCP pool that aren't recorded yet have
  // ip_id == null, so we fall through to a create-at-address flow.
  if (entry.ip_id != null) {
    try {
      const hit = await ipsApi.get(entry.ip_id)
      editingIpFor.value = { ip: hit, address: null }
      return
    } catch (err) {
      // Stale grid: another admin deleted the row between the page load
      // and this click. Don't strand the user on the error toast — fall
      // through to a create-at-address flow so the click still does
      // something useful. Same behaviour as the pre-`ip_id` code path
      // (Codex P2 on #76).
      if (err instanceof ApiError && err.status === 404) {
        editingIpFor.value = { ip: null, address: entry.address }
        return
      }
      void describe(err)
      return
    }
  }
  editingIpFor.value = { ip: null, address: entry.address }
}

const ipColumns: DataTableColumn[] = [
  { key: 'address', label: t('ip.fields.address'), cellClass: 'font-mono w-40' },
  { key: 'status', label: t('ip.fields.status'), cellClass: 'w-28' },
  { key: 'hostname', label: t('ip.fields.hostname') },
  { key: 'mac', label: t('ip.fields.mac'), cellClass: 'font-mono', hideOnSm: true },
  { key: 'description', label: t('ip.fields.description'), hideOnSm: true },
]

// Client-side filter on the table view — the data is already in memory
// (the /ips endpoint capped at /20 = 4096 rows), so a substring scan over
// `hostname/mac/description/address` is cheap and avoids a round-trip per
// keystroke. The status pill works the same way: filter the loaded list,
// don't re-fetch.
const ipSearch = ref('')
const ipStatusFilter = ref<'all' | 'assigned' | 'reserved' | 'dhcp' | 'free'>('all')

const filteredIps = computed(() => {
  const needle = ipSearch.value.trim().toLowerCase()
  return ips.value.filter((entry) => {
    if (ipStatusFilter.value !== 'all' && entry.status !== ipStatusFilter.value) {
      return false
    }
    if (!needle) return true
    // Match on every searchable text field. Address is checked too so an
    // operator typing the last octet ("42") still lands on .42 rows.
    return (
      entry.address.toLowerCase().includes(needle) ||
      (entry.hostname?.toLowerCase().includes(needle) ?? false) ||
      (entry.mac?.toLowerCase().includes(needle) ?? false) ||
      (entry.description?.toLowerCase().includes(needle) ?? false)
    )
  })
})

const tableRows = computed(() => filteredIps.value.map((entry) => ({ ...entry, id: entry.address })))

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
  <div class="p-4 sm:p-6 max-w-7xl mx-auto">
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
          <!-- "Next free" is read-only to viewers — they get the toast but
               not the editor follow-up. Useful so a NOC operator can plan
               an assignment before pinging the admin. -->
          <Button variant="secondary" @click="suggestNextFree">
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

      <!-- View toggle + table filters. Filters only matter in table view;
           the grid view stays a visual heatmap and re-rendering 4096 buttons
           on every keystroke isn't what an operator wants. Hidden when the
           subnet is too large to enumerate — the banner below explains why
           and what to do instead. -->
      <div v-if="!tooLarge" class="flex flex-wrap items-center justify-between gap-3 mb-3">
        <h2 class="text-lg font-semibold">{{ t('ip.labelPlural') }}</h2>
        <div class="flex flex-wrap items-center gap-2">
          <template v-if="view === 'table'">
            <select
              v-model="ipStatusFilter"
              class="h-7 px-2 rounded border border-border bg-surface text-xs"
              :aria-label="t('ip.fields.status')"
            >
              <option value="all">{{ t('ip.statusFilter.all') }}</option>
              <option value="assigned">{{ t('ip.status.assigned') }}</option>
              <option value="reserved">{{ t('ip.status.reserved') }}</option>
              <option value="dhcp">{{ t('ip.status.dhcp') }}</option>
              <option value="free">{{ t('ip.status.free') }}</option>
            </select>
            <input
              v-model="ipSearch"
              type="search"
              :placeholder="t('ip.searchPlaceholder')"
              :aria-label="t('ip.searchPlaceholder')"
              class="h-7 px-2 rounded border border-border bg-surface text-xs w-44"
              autocomplete="off"
              spellcheck="false"
            />
          </template>
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
      </div>

      <!-- Subnet too large to enumerate. The utilisation card above still
           shows the fill rate (cheap COUNT, no scan), and the operator can
           use the search/export/next-free actions — but the grid /
           per-address table can't render the full address space. Better
           than the previous behaviour where the grid silently rendered
           empty, looking like the subnet had no IPs at all. -->
      <div
        v-if="tooLarge"
        class="nf-card p-5 border-l-4 border-warning"
        role="status"
      >
        <p class="text-sm font-semibold text-fg flex items-center gap-2">
          <span class="inline-block w-2 h-2 rounded-full bg-warning" aria-hidden="true" />
          {{ t('subnet.tooLargeTitle') }}
        </p>
        <p class="mt-2 text-sm text-fg-muted">
          {{ t('subnet.tooLargeBody', { cidr: subnet.cidr }) }}
        </p>
        <ul class="mt-3 text-sm text-fg-muted list-disc pl-5 space-y-1">
          <li>{{ t('subnet.tooLargeHint.splitChildren') }}</li>
          <li>{{ t('subnet.tooLargeHint.useExport') }}</li>
          <li>{{ t('subnet.tooLargeHint.useImport') }}</li>
        </ul>
      </div>

      <!-- Grid view -->
      <div v-else-if="view === 'grid'" class="nf-card p-4">
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
