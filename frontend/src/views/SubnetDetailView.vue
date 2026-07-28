<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  AlertTriangle,
  Download,
  Grid3x3,
  Layers,
  Pencil,
  Sparkles,
  Table as TableIcon,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Breadcrumb from '@/components/Breadcrumb.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import Segmented, { type SegmentedOption } from '@/components/ui/Segmented.vue'
import Select from '@/components/ui/Select.vue'
import VlanBadge from '@/components/VlanBadge.vue'
import SubnetFillBar from '@/components/SubnetFillBar.vue'
import IpGrid from '@/components/IpGrid.vue'
import BulkIpDialog from '@/components/editors/BulkIpDialog.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import { useStoredRef } from '@/composables/useStoredRef'
import { ApiError, ipsApi, subnetsApi, vlansApi } from '@/api'
import type { Subnet, SubnetIpEntry, SubnetUtilization, Vlan } from '@/api'

// `ip_id` was added to SubnetIpEntry in PR perf/ipam-indexes-and-group-by
// so the editor can be opened with one fetch instead of two. The optional
// chain keeps the code working against older API responses (the field is
// nullable for synthetic free/dhcp rows anyway).
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { isAdmin } = useAuth()
const { info } = useToast()
const { notify } = useApiErrorMessage()

const subnet = ref<Subnet | null>(null)
const ips = ref<SubnetIpEntry[]>([])
const vlan = ref<Vlan | null>(null)
const utilization = ref<SubnetUtilization | null>(null)
const loading = ref(true)
// Persist the view mode across reloads — admins flipping between grid and
// table once expect that choice to stick on the same machine.
const view = useStoredRef<'grid' | 'table'>('netforge.subnet.view', 'grid')

const bulkOpen = ref(false)
// True when `/ips` refused to enumerate the address space because the
// subnet is bigger than the server-side cap (`SUBNET_TOO_LARGE`). The
// utilisation card still renders — we just hide the grid and surface
// an explicit explanation so the operator doesn't read "empty grid" as
// "empty subnet".
const tooLarge = ref(false)

const id = computed(() => Number(route.params.id))

// Sequence guard — `watch(id, load)` re-fires when the user navigates
// between adjacent subnet detail pages quickly. Without this token, the
// stale response from the previous subnet can overwrite the fresh view.
let detailLoadSeq = 0

async function load() {
  const seq = ++detailLoadSeq
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
    if (seq !== detailLoadSeq) return
    subnet.value = s
    utilization.value = util
    vlan.value = s.vlan_id ? await vlansApi.get(s.vlan_id) : null
    if (seq !== detailLoadSeq) return
    try {
      const list = await subnetsApi.ips(id.value)
      if (seq !== detailLoadSeq) return
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
    if (seq !== detailLoadSeq) return
    notify(err)
    router.replace('/subnets')
  } finally {
    if (seq === detailLoadSeq) loading.value = false
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

// Grid / table switch. Same control the switch detail page and the list
// pages use, so the toggle behaves identically wherever it appears.
const viewOptions = computed<SegmentedOption<'grid' | 'table'>[]>(() => [
  { value: 'grid', label: t('subnet.viewGrid'), icon: Grid3x3 },
  { value: 'table', label: t('subnet.viewTable'), icon: TableIcon },
])

// Create and edit are full pages, not modals — see components/FormPage.vue.
// The address to pre-fill travels as a query param on the create route.
function openIpCreate(address: string) {
  if (!subnet.value) return
  router.push({ name: 'ip-new', params: { subnetId: subnet.value.id }, query: { address } })
}

function editSubnet() {
  if (!subnet.value) return
  // `from` sends the user back here after saving rather than to the list.
  router.push({
    name: 'subnet-edit',
    params: { id: subnet.value.id },
    query: { from: route.fullPath },
  })
}

async function suggestNextFree() {
  if (!subnet.value) return
  try {
    const res = await subnetsApi.nextFree(subnet.value.id)
    info(t('subnet.nextFreeFound', { address: res.address }))
    // Admins flow straight into the IP form with the suggestion
    // prefilled — one less click to actually assign. Viewers get the
    // toast and nothing else; the backend endpoint is open to them too,
    // but they have no write capability to follow up with.
    if (isAdmin.value) {
      openIpCreate(res.address)
    }
  } catch (err) {
    if (err instanceof ApiError && err.code === 'SUBNET_FULL') {
      info(t('subnet.nextFreeNone'))
      return
    }
    notify(err)
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
    openIpCreate(entry.address)
    return
  }
  // The entry carries `ip_id` when the row exists in the DB — go straight to
  // the edit page for it. Synthetic "dhcp" rows for addresses inside a DHCP
  // pool that aren't recorded yet have ip_id == null, so we fall through to
  // a create-at-address flow. The GET is kept as a liveness probe: it is what
  // tells a stale grid apart from a live row before we navigate.
  if (entry.ip_id != null) {
    try {
      const hit = await ipsApi.get(entry.ip_id)
      router.push({ name: 'ip-edit', params: { id: hit.id } })
      return
    } catch (err) {
      // Stale grid: another admin deleted the row between the page load
      // and this click. Don't strand the user on the error toast — fall
      // through to a create-at-address flow so the click still does
      // something useful. Same behaviour as the pre-`ip_id` code path
      // (Codex P2 on #76).
      if (err instanceof ApiError && err.status === 404) {
        openIpCreate(entry.address)
        return
      }
      notify(err)
      return
    }
  }
  openIpCreate(entry.address)
}

// Wrap in computed so labels follow the i18n locale.
const ipColumns = computed<DataTableColumn[]>(() => [
  { key: 'address', label: t('ip.fields.address'), cellClass: 'font-mono w-40' },
  { key: 'status', label: t('ip.fields.status'), cellClass: 'w-28' },
  { key: 'hostname', label: t('ip.fields.hostname') },
  { key: 'mac', label: t('ip.fields.mac'), cellClass: 'font-mono', hideOnSm: true },
  { key: 'description', label: t('ip.fields.description'), hideOnSm: true },
])

// Client-side filter on the table view — the data is already in memory
// (the /ips endpoint capped at /20 = 4096 rows), so a substring scan over
// `hostname/mac/description/address` is cheap and avoids a round-trip per
// keystroke. The status pill works the same way: filter the loaded list,
// don't re-fetch.
const ipSearch = ref('')
type IpStatusFilter = 'all' | 'assigned' | 'reserved' | 'dhcp' | 'free'
const ipStatusFilter = ref<IpStatusFilter>('all')

// Computed so the labels follow a locale switch, like `columns` further down.
const ipStatusOptions = computed<{ value: IpStatusFilter; label: string }[]>(() => [
  { value: 'all', label: t('ip.statusFilter.all') },
  { value: 'assigned', label: t('ip.status.assigned') },
  { value: 'reserved', label: t('ip.status.reserved') },
  { value: 'dhcp', label: t('ip.status.dhcp') },
  { value: 'free', label: t('ip.status.free') },
])

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

const tableRows = computed(() =>
  filteredIps.value.map((entry) => ({ ...entry, id: entry.address })),
)

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
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <div v-if="loading && !subnet" aria-busy="true">
      <div class="mb-3">
        <Skeleton width="14rem" height="0.75rem" />
      </div>
      <div class="mb-8">
        <Skeleton width="14rem" height="1.75rem" rounded="md" />
        <div class="mt-2">
          <Skeleton width="24rem" height="0.875rem" />
        </div>
      </div>
      <!-- Mirrors the identity block below: one card, four hairline-separated cells. -->
      <section class="nf-card overflow-hidden mb-6">
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px bg-border">
          <div v-for="i in 4" :key="`sk-meta-${i}`" class="bg-surface px-5 py-4">
            <Skeleton width="5rem" height="0.625rem" />
            <div class="mt-2.5">
              <Skeleton width="80%" height="0.875rem" />
            </div>
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
          <Button v-if="isAdmin" variant="secondary" @click="bulkOpen = true">
            <Layers class="w-4 h-4" aria-hidden="true" />
            {{ t('subnet.bulk.open') }}
          </Button>
          <Button v-if="isAdmin" variant="primary" @click="editSubnet">
            <Pencil class="w-4 h-4" aria-hidden="true" />
            {{ t('common.edit') }}
          </Button>
        </template>
      </PageHeader>

      <!-- Identity. One card, hairline-separated cells: the page opens with
           what this subnet *is* rather than four disconnected boxes. The
           `gap-px` over a `bg-border` container draws the dividers, so they
           land correctly at every breakpoint without per-cell border rules. -->
      <section class="nf-card overflow-hidden mb-8">
        <dl class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px bg-border">
          <div class="bg-surface px-5 py-4 min-w-0">
            <dt class="nf-label">{{ t('subnet.fields.vlan') }}</dt>
            <dd class="mt-2">
              <VlanBadge v-if="vlan" :vlan="vlan" />
              <span v-else class="text-base text-fg-subtle">—</span>
            </dd>
          </div>
          <div class="bg-surface px-5 py-4 min-w-0">
            <dt class="nf-label">{{ t('subnet.fields.gateway') }}</dt>
            <dd class="mt-2 font-mono text-base text-fg truncate">
              {{ subnet.gateway || '—' }}
            </dd>
          </div>
          <div class="bg-surface px-5 py-4 min-w-0">
            <dt class="nf-label">{{ t('subnet.fields.dhcp') }}</dt>
            <dd
              class="mt-2 text-base text-fg truncate"
              :title="
                subnet.dhcp_enabled
                  ? `${subnet.dhcp_range_start} → ${subnet.dhcp_range_end}`
                  : undefined
              "
            >
              <span v-if="subnet.dhcp_enabled" class="font-mono">
                {{ subnet.dhcp_range_start }} → {{ subnet.dhcp_range_end }}
              </span>
              <span v-else class="text-fg-subtle">{{ t('common.no') }}</span>
            </dd>
          </div>
          <div class="bg-surface px-5 py-4 min-w-0">
            <dt class="nf-label">{{ t('subnet.fields.usage') }}</dt>
            <!-- Same component, same green / amber / red ramp as the lists and
                 the dashboard, so a fill rate reads identically everywhere. -->
            <dd class="mt-2">
              <SubnetFillBar :used="stats.used" :usable="stats.total" variant="block" />
            </dd>
          </div>
        </dl>
      </section>

      <!-- IPs. Heading on the left, controls on the right — same shape as the
           list pages. Status pill + free-text filter only show in table view:
           they don't apply to the grid heatmap, and rendering them when the
           user toggles back to grid would just clutter the row. -->
      <section>
        <div v-if="!tooLarge" class="nf-toolbar justify-between">
          <div class="flex items-baseline gap-2 min-w-0">
            <h2 class="nf-section-title">{{ t('ip.labelPlural') }}</h2>
            <span class="text-sm text-fg-subtle tabular-nums">{{ ips.length }}</span>
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <template v-if="view === 'table'">
              <div class="min-w-[9rem]">
                <Select
                  v-model="ipStatusFilter"
                  :options="ipStatusOptions"
                  :aria-label="t('ip.fields.status')"
                />
              </div>
              <input
                v-model="ipSearch"
                type="search"
                :placeholder="t('ip.searchPlaceholder')"
                :aria-label="t('ip.searchPlaceholder')"
                class="nf-input nf-input-control w-48"
                autocomplete="off"
                spellcheck="false"
              />
            </template>
            <Segmented v-model="view" :options="viewOptions" :aria-label="t('ip.labelPlural')" />
          </div>
        </div>

        <!-- Subnet too large to enumerate. The identity block above still
             shows the fill rate (cheap COUNT, no scan), and the operator can
             use the search/export/next-free actions — but the grid /
             per-address table can't render the full address space. Better
             than the previous behaviour where the grid silently rendered
             empty, looking like the subnet had no IPs at all. -->
        <!-- Informational, not a failure: an amber caution plate rather than a
             fault. Same LED vocabulary the dashboard capacity buckets use. -->
        <div v-if="tooLarge" class="nf-card p-5 flex items-start gap-4" role="status">
          <span
            class="inline-flex items-center justify-center w-9 h-9 rounded-md flex-shrink-0 bg-warning/10 border border-warning/30 text-warning"
            aria-hidden="true"
          >
            <AlertTriangle class="w-4 h-4" />
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-base font-semibold text-fg">{{ t('subnet.tooLargeTitle') }}</p>
            <p class="mt-1 text-base text-fg-muted">
              {{ t('subnet.tooLargeBody', { cidr: subnet.cidr }) }}
            </p>
            <ul class="mt-3 text-sm text-fg-muted list-disc pl-5 space-y-1">
              <li>{{ t('subnet.tooLargeHint.splitChildren') }}</li>
              <li>{{ t('subnet.tooLargeHint.useExport') }}</li>
              <li>{{ t('subnet.tooLargeHint.useImport') }}</li>
            </ul>
          </div>
        </div>

        <!-- Grid view -->
        <div v-else-if="view === 'grid'" class="nf-card p-4 sm:p-5">
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
          <template #cell-address="{ row }">
            <span class="font-mono text-base text-fg">{{ row.address }}</span>
          </template>
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
      </section>

      <BulkIpDialog :open="bulkOpen" :subnet="subnet" @close="bulkOpen = false" @applied="load" />
    </template>
  </div>
</template>
