<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { List, Network, Plus, Pencil, Search, Trash2, X } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import EmptyState from '@/components/EmptyState.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Input from '@/components/ui/Input.vue'
import Segmented from '@/components/ui/Segmented.vue'
import Select from '@/components/ui/Select.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import VlanBadge from '@/components/VlanBadge.vue'
import SubnetTreeRow from '@/components/SubnetTreeRow.vue'
import SubnetFillBar from '@/components/SubnetFillBar.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { fetchAllPages, sitesApi, subnetsApi, vlansApi } from '@/api'
import type { Site, Subnet, Vlan } from '@/api'
import type { SubnetTreeNode } from '@/api/endpoints/subnets'
import { vrfsApi } from '@/api/endpoints/vrfs'
import type { Vrf } from '@/api/endpoints/vrfs'
import { useAuth } from '@/composables/useAuth'
import { useDebounce } from '@/composables/useDebounce'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const { t } = useI18n()
const { isAdmin } = useAuth()
const { success } = useToast()
const { notify } = useApiErrorMessage()
const router = useRouter()

const items = ref<Subnet[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)

const vlans = ref<Vlan[]>([])
const vlansById = ref<Map<number, Vlan>>(new Map())
const sites = ref<Site[]>([])
const vrfs = ref<Vrf[]>([])
// Filter chip values:
//   undefined → show every subnet across all VRFs (default list mode)
//   0         → show only the global-scope subnets (vrf_id IS NULL)
//   N (>0)    → show only the subnets in VRF N
// The tree view re-uses the same filter; it always shows a single scope at
// a time (global by default, or a specific VRF when picked).
//
// The dropdown always holds a concrete value, so "no filter" travels through
// it as a sentinel. 0 is already spoken for (global scope) and every real id
// is positive, which leaves -1 as the only free slot. It never escapes the
// template: the change handlers map it straight back to `undefined`.
const FILTER_ALL = -1
const vrfFilter = ref<number | undefined>(undefined)
const siteFilter = ref<number | undefined>(undefined)
const vlanFilter = ref<number | undefined>(undefined)
// Free-text search — `searchInput` is what the user types, `searchQuery`
// is debounced and the value that actually hits the API. Server-side
// search is trigram-indexed (migration 0012), so even on large bases the
// 200ms debounce is enough to keep keystrokes responsive without
// hammering the backend on every key.
const searchInput = ref('')
const searchQuery = useDebounce(searchInput, 200)

const viewMode = ref<'list' | 'tree'>('list')
const tree = ref<SubnetTreeNode[]>([])
const treeLoading = ref(false)
const collapsed = ref<Set<number>>(new Set())

const deleteTarget = ref<Subnet | null>(null)
const deleting = ref(false)

// Monotonic sequence counter so a stale in-flight response from an earlier
// filter combination can't overwrite the fresh data. Each load() call snapshots
// the next sequence id; the response is only applied when our token is still
// the latest. Without this, toggling filters quickly on a slow backend lets
// older responses win and the visible rows lag the active filter.
let listLoadSeq = 0
let treeLoadSeq = 0

async function load() {
  const seq = ++listLoadSeq
  loading.value = true
  try {
    const res = await subnetsApi.list({
      page: page.value,
      page_size: pageSize,
      vrf_id: vrfFilter.value,
      site_id: siteFilter.value,
      vlan_id: vlanFilter.value,
      q: searchQuery.value.trim() || undefined,
    })
    if (seq !== listLoadSeq) return // a newer call has been issued — discard.
    items.value = res.items
    total.value = res.total
  } finally {
    if (seq === listLoadSeq) loading.value = false
  }
}

async function loadTree() {
  const seq = ++treeLoadSeq
  treeLoading.value = true
  try {
    // Map the chip back to the tree endpoint: undefined / 0 = global.
    // Site + VLAN narrow the result; the backend handles the orphan
    // promotion so filtering by a leaf VLAN still surfaces matches.
    const res = await subnetsApi.tree({
      vrf_id: vrfFilter.value && vrfFilter.value > 0 ? vrfFilter.value : 0,
      site_id: siteFilter.value,
      vlan_id: vlanFilter.value,
    })
    if (seq !== treeLoadSeq) return
    tree.value = res
  } finally {
    if (seq === treeLoadSeq) treeLoading.value = false
  }
}

async function loadVlans() {
  // VLANs feed two things: the badge lookup map for each subnet row AND the
  // VLAN filter chip. Pull the full list once and share it.
  //
  // The server hard-caps `page_size` at 200 (`PageParams`,
  // backend/app/schemas/common.py) — asking for 500 returned 422 on every
  // load, which left the VLAN filter permanently empty and every row's VLAN
  // badge unresolved. `fetchAllPages` walks the pages so deployments past
  // 200 VLANs still resolve every badge. Failure is non-fatal: the list
  // still renders without VLAN context.
  try {
    const items = await fetchAllPages((p) => vlansApi.list(p))
    vlans.value = items
    vlansById.value = new Map(items.map((v) => [v.id, v]))
  } catch {
    vlans.value = []
    vlansById.value = new Map()
  }
}

async function loadSites() {
  try {
    sites.value = await fetchAllPages((p) => sitesApi.list(p))
  } catch {
    sites.value = []
  }
}

async function loadVrfs() {
  try {
    vrfs.value = await vrfsApi.list()
  } catch {
    // Non-blocking — UI just hides the picker if the call failed.
    vrfs.value = []
  }
}

function reloadCurrentView() {
  page.value = 1
  if (viewMode.value === 'tree') {
    loadTree()
  } else {
    load()
  }
}

function onVrfFilterChange(value: number | undefined) {
  vrfFilter.value = value
  reloadCurrentView()
}

function onSiteFilterChange(value: number | undefined) {
  siteFilter.value = value
  // Both views now respect site/vlan filters — list passes them as
  // query params, tree passes them to `/subnets/tree` which prunes
  // non-matching nodes and floats matching descendants to root level.
  reloadCurrentView()
}

function onVlanFilterChange(value: number | undefined) {
  vlanFilter.value = value
  reloadCurrentView()
}

function clearFilters() {
  searchInput.value = ''
  // Force-settle the debounced search so the subsequent load() sees the
  // empty query, not the 200ms-stale value. Without this, the load fired
  // by reloadCurrentView reads the OLD `searchQuery` and re-issues the
  // request with the previous query still attached; the debounce fires a
  // second load 200ms later and the two race — older response wins ⇒ the
  // user sees the previously-filtered subset after explicitly clearing.
  searchQuery.flush()
  siteFilter.value = undefined
  vlanFilter.value = undefined
  vrfFilter.value = undefined
  reloadCurrentView()
}

const hasActiveFilters = computed(
  () =>
    searchInput.value.trim().length > 0 ||
    siteFilter.value !== undefined ||
    vlanFilter.value !== undefined ||
    vrfFilter.value !== undefined,
)

// React to debounced search input. We re-fire on every change including
// the empty string so clearing the field restores the full list — the
// `q?: undefined` in `load()` strips it from the params.
watch(searchQuery, () => {
  // Search affects the list view only — the tree builder doesn't take
  // `q` (would break the parent/child hierarchy). Switch the user back
  // to list view automatically the moment they start typing.
  if (viewMode.value !== 'list') viewMode.value = 'list'
  page.value = 1
  load()
})

function switchView(mode: 'list' | 'tree') {
  viewMode.value = mode
  if (mode === 'tree') {
    loadTree()
  } else {
    load()
  }
}

const viewOptions = computed(() => [
  { value: 'list' as const, label: t('subnet.viewList'), icon: List },
  { value: 'tree' as const, label: t('subnet.viewTree'), icon: Network },
])

// Filter dropdowns. Computed so the labels re-render on a locale switch —
// same reason `columns` below is computed.
//
// The first entry means "don't filter"; in tree view that is the global
// scope, which is why its label changes with the view mode. The explicit
// `0` row stays regardless: in list view it narrows to global-scope subnets
// only, which is a different result from "every VRF".
const vrfFilterOptions = computed(() => [
  {
    value: FILTER_ALL,
    label: viewMode.value === 'list' ? t('subnet.vrfFilterAll') : t('subnet.vrfFilterGlobal'),
  },
  { value: 0, label: t('subnet.vrfFilterGlobal') },
  ...vrfs.value.map((v) => ({ value: v.id, label: v.name })),
])

const siteFilterOptions = computed(() => [
  { value: FILTER_ALL, label: t('subnet.allSites') },
  ...sites.value.map((s) => ({ value: s.id, label: s.code })),
])

const vlanFilterOptions = computed(() => [
  { value: FILTER_ALL, label: t('subnet.allVlans') },
  ...vlans.value.map((v) => ({ value: v.id, label: `${v.vlan_id} — ${v.name}` })),
])

// The tree endpoint returns a nested structure rather than a page, so the
// honest "how many am I looking at" number is the count of real subnets in
// it — synthetic auto-group supernets have no DB row and aren't counted.
function countRealNodes(nodes: SubnetTreeNode[]): number {
  return nodes.reduce((n, node) => n + (node.synthetic ? 0 : 1) + countRealNodes(node.children), 0)
}

const resultCount = computed(() =>
  viewMode.value === 'tree' ? countRealNodes(tree.value) : total.value,
)

function toggleNode(id: number) {
  if (collapsed.value.has(id)) collapsed.value.delete(id)
  else collapsed.value.add(id)
  // Force reactivity — Set mutations don't auto-trigger.
  collapsed.value = new Set(collapsed.value)
}

function openSubnet(id: number) {
  router.push(`/subnets/${id}`)
}

onMounted(() => {
  load()
  loadVlans()
  loadVrfs()
  loadSites()
})

// Create and edit are full pages, not modals — see components/FormPage.vue.
function onNew() {
  router.push({ name: 'subnet-new' })
}

function onEdit(s: Subnet) {
  router.push({ name: 'subnet-edit', params: { id: s.id } })
}

function onRowClick(s: Subnet) {
  router.push(`/subnets/${s.id}`)
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await subnetsApi.delete(deleteTarget.value.id)
    success(t('common.success'))
    deleteTarget.value = null
    load()
  } catch (err) {
    notify(err)
  } finally {
    deleting.value = false
  }
}

// Wrap in computed so `t()` re-runs when the user switches the UI
// locale via LocaleSwitcher — otherwise the column header labels stay
// frozen at the language active when the component mounted. Matches
// the pattern PortTable.vue already uses correctly.
const columns = computed<DataTableColumn[]>(() => [
  { key: 'cidr', label: t('subnet.fields.cidr') },
  { key: 'vlan_id', label: t('subnet.fields.vlan'), cellClass: 'w-40' },
  { key: 'gateway', label: t('subnet.fields.gateway'), hideOnSm: true, cellClass: 'font-mono' },
  { key: 'description', label: t('subnet.fields.description'), hideOnSm: true },
  { key: 'usage', label: t('subnet.fields.usage'), cellClass: 'w-40' },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
])
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="t('subnet.labelPlural')" :subtitle="t('subnet.subtitle')">
      <template #help>
        <HelpTooltip :text="t('subnet.pageHelp')" placement="bottom" />
      </template>
      <template #actions>
        <Button v-if="isAdmin" variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('subnet.new') }}
        </Button>
      </template>
    </PageHeader>

    <!-- Toolbar — the same shape on every list page: search first, then the
         scope filters, then the result count and the view switch pushed to
         the right. "Clear filters" only appears once something is filtering
         so the bar stays calm by default. -->
    <div class="nf-toolbar">
      <div class="relative flex-1 min-w-[14rem] max-w-sm">
        <Search
          class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-fg-subtle pointer-events-none z-10"
          aria-hidden="true"
        />
        <Input
          v-model="searchInput"
          type="search"
          :placeholder="t('subnet.searchPlaceholder')"
          :aria-label="t('subnet.searchPlaceholder')"
          class="pl-9 pr-9"
          autocomplete="off"
          spellcheck="false"
        />
        <button
          v-if="searchInput"
          type="button"
          class="absolute right-1.5 top-1/2 -translate-y-1/2 inline-flex items-center justify-center w-6 h-6 rounded text-fg-muted hover:bg-surface-hover hover:text-fg transition-colors duration-150 ease-soft"
          :aria-label="t('common.reset')"
          @click="searchInput = ''"
        >
          <X class="w-3.5 h-3.5" aria-hidden="true" />
        </button>
      </div>

      <!-- Scope filters. Each one is hidden when there's nothing to pick
           from (single-site / no-VLAN deployments) instead of rendering an
           empty dropdown. -->
      <div class="min-w-[9rem]">
        <Select
          :model-value="vrfFilter ?? FILTER_ALL"
          :options="vrfFilterOptions"
          :aria-label="t('subnet.vrfFilter')"
          @update:model-value="(v) => onVrfFilterChange(v === FILTER_ALL ? undefined : v)"
        />
      </div>

      <div v-if="sites.length > 0" class="min-w-[9rem]">
        <Select
          :model-value="siteFilter ?? FILTER_ALL"
          :options="siteFilterOptions"
          :aria-label="t('subnet.fields.site')"
          @update:model-value="(v) => onSiteFilterChange(v === FILTER_ALL ? undefined : v)"
        />
      </div>

      <div v-if="vlans.length > 0" class="min-w-[9rem]">
        <Select
          :model-value="vlanFilter ?? FILTER_ALL"
          :options="vlanFilterOptions"
          :aria-label="t('subnet.fields.vlan')"
          @update:model-value="(v) => onVlanFilterChange(v === FILTER_ALL ? undefined : v)"
        />
      </div>

      <Button v-if="hasActiveFilters" variant="ghost" size="sm" @click="clearFilters">
        <X class="w-3.5 h-3.5" aria-hidden="true" />
        {{ t('common.clearFilters') }}
      </Button>

      <div class="ml-auto flex items-center gap-3">
        <span class="text-sm text-fg-muted tabular-nums whitespace-nowrap" aria-live="polite">
          {{ t('common.resultCount', resultCount) }}
        </span>
        <Segmented
          :model-value="viewMode"
          :options="viewOptions"
          :aria-label="t('subnet.labelPlural')"
          @update:model-value="switchView"
        />
      </div>
    </div>

    <!-- Tree view. Read-only hierarchical view — `parent_subnet_id` is
         editable from the subnet form, not by dragging rows. -->
    <div v-if="viewMode === 'tree'" class="nf-card overflow-hidden">
      <div v-if="treeLoading" class="divide-y divide-border/50">
        <div v-for="i in 6" :key="`sk-tree-${i}`" class="px-4 py-3.5" :aria-busy="true">
          <Skeleton :width="`${70 - i * 6}%`" height="0.875rem" rounded="sm" />
        </div>
      </div>
      <EmptyState
        v-else-if="tree.length === 0"
        :icon="Network"
        :title="hasActiveFilters ? t('common.noMatch.title') : t('common.empty.title')"
        :description="hasActiveFilters ? t('common.noMatch.description') : t('subnet.treeEmpty')"
      >
        <template #action>
          <Button v-if="hasActiveFilters" variant="secondary" @click="clearFilters">
            <X class="w-4 h-4" aria-hidden="true" />
            {{ t('common.clearFilters') }}
          </Button>
          <Button v-else-if="isAdmin" variant="primary" @click="onNew">
            <Plus class="w-4 h-4" aria-hidden="true" />
            {{ t('subnet.new') }}
          </Button>
        </template>
      </EmptyState>
      <ul v-else class="divide-y divide-border/50">
        <SubnetTreeRow
          v-for="(node, idx) in tree"
          :key="node.id"
          :node="node"
          :collapsed="collapsed"
          :depth="0"
          :is-last="idx === tree.length - 1"
          :vlans-by-id="vlansById"
          @toggle="toggleNode"
          @open="openSubnet"
        />
      </ul>
    </div>

    <DataTable
      v-else
      :columns="columns"
      :rows="items"
      :loading="loading"
      :empty-title="hasActiveFilters ? t('common.noMatch.title') : t('common.empty.title')"
      :empty-description="hasActiveFilters ? t('common.noMatch.description') : t('subnet.empty')"
      clickable
      @row-click="onRowClick"
    >
      <template #empty-action>
        <Button v-if="hasActiveFilters" variant="secondary" @click="clearFilters">
          <X class="w-4 h-4" aria-hidden="true" />
          {{ t('common.clearFilters') }}
        </Button>
        <Button v-else-if="isAdmin" variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('subnet.new') }}
        </Button>
      </template>
      <template #cell-vlan_id="{ row }">
        <VlanBadge
          v-if="row.vlan_id && vlansById.get(row.vlan_id)"
          :vlan="vlansById.get(row.vlan_id)!"
        />
        <Badge v-else tone="muted">—</Badge>
      </template>
      <!-- The CIDR is the thing you click: it carries the row's identity and
           picks up the accent on row hover so the target is unambiguous. -->
      <template #cell-cidr="{ row }">
        <span
          class="font-mono text-base font-medium text-fg group-hover/row:text-primary-600 dark:group-hover/row:text-primary-400 transition-colors duration-150 ease-soft"
        >
          {{ row.cidr }}
        </span>
      </template>
      <template #cell-gateway="{ row }">
        <span class="font-mono text-fg-muted">{{ row.gateway || '—' }}</span>
      </template>
      <template #cell-description="{ row }">
        <span class="text-fg-muted">{{ row.description || '—' }}</span>
      </template>
      <template #cell-usage="{ row }">
        <SubnetFillBar
          :used="row.used ?? 0"
          :usable="row.usable ?? 0"
          variant="full"
          bar-class="w-20"
        />
      </template>
      <template #cell-actions="{ row }">
        <div class="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="sm"
            :aria-label="t('common.edit')"
            :disabled="!isAdmin"
            @click.stop="onEdit(row)"
          >
            <Pencil class="w-4 h-4" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :aria-label="t('common.delete')"
            :disabled="!isAdmin"
            @click.stop="deleteTarget = row"
          >
            <Trash2 class="w-4 h-4 text-danger" aria-hidden="true" />
          </Button>
        </div>
      </template>
      <template #footer>
        <Pagination
          v-if="total > pageSize"
          :page="page"
          :page-size="pageSize"
          :total="total"
          @update:page="
            (p) => {
              page = p
              load()
            }
          "
        />
      </template>
    </DataTable>

    <ConfirmDialog
      :open="!!deleteTarget"
      :title="t('common.confirmDelete.title', { label: deleteTarget?.cidr ?? '' })"
      :message="t('common.confirmDelete.message')"
      variant="danger"
      :loading="deleting"
      @confirm="confirmDelete"
      @cancel="deleteTarget = null"
    />
  </div>
</template>
