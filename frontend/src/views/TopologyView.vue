<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Cable,
  Download,
  HardDrive,
  LayoutGrid,
  List as ListIcon,
  Maximize,
  Network,
  Pencil,
  Plus,
  RotateCcw,
  Server,
  Sparkles,
  Trash2,
  TriangleAlert,
  X as XIcon,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Button from '@/components/ui/Button.vue'
import Select from '@/components/ui/Select.vue'
import Segmented from '@/components/ui/Segmented.vue'
import Badge from '@/components/ui/Badge.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import TopologyCanvas, { type LayoutName } from '@/components/TopologyCanvas.vue'
import LinkEditor from '@/components/editors/LinkEditor.vue'
import LinkSuggestionsModal from '@/components/ai/LinkSuggestionsModal.vue'
import {
  aiApi,
  fetchAllPages,
  linksApi,
  roomsApi,
  sitesApi,
  switchesApi,
  topologyApi,
  vlansApi,
} from '@/api'
import type {
  AIStatus,
  Link,
  Room,
  Site,
  Switch,
  TopologyEdgeData,
  TopologyNodeData,
  TopologyResponse,
  TopologyStats,
  Vlan,
} from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'
import { useAuth } from '@/composables/useAuth'

/**
 * The topology page has two views over one payload.
 *
 * The graph is the pointer-driven one: compound site/room boxes, plates for
 * switches and devices, and a focus mode that dims everything outside the
 * selected node's neighbourhood. The list is the same nodes and edges as two
 * real tables — it is the accessible path (the canvas has no keyboard model
 * of its own) and also the faster one for "which switch has a free port".
 *
 * Filters are server-side: every change is one request, so the payload and
 * its `stats` always describe exactly what is on screen.
 */

const { t, n } = useI18n()
const router = useRouter()
const { describe } = useApiErrorMessage()
const { error: toastError, success: toastSuccess } = useToast()
const { isAdmin } = useAuth()

type ViewMode = 'graph' | 'list'

const graph = ref<TopologyResponse | null>(null)
const loading = ref(true)
const sites = ref<Site[]>([])
const rooms = ref<Room[]>([])
const vlans = ref<Vlan[]>([])
// Only needed to hand LinkEditor a switch list it would otherwise refetch.
const switches = ref<Switch[]>([])

// AI surface state. Loaded once on mount; the Suggest button only appears when
// the backend reports `enabled`, so self-hosters without an API key never see
// a control that cannot work.
const aiStatus = ref<AIStatus | null>(null)
const aiModalOpen = ref(false)

const viewMode = ref<ViewMode>('graph')
const layout = ref<LayoutName>('dagre')
const siteFilter = ref(0) // 0 = every site
const roomFilter = ref(0)
const vlanFilter = ref(0)
const showDevices = ref(true)
const selectedId = ref<string | null>(null)

const canvasRef = ref<InstanceType<typeof TopologyCanvas> | null>(null)

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

// Guards against a slow response for a filter the user has already changed
// landing after a fast one for the filter now selected.
let loadSeq = 0

async function loadGraph() {
  const seq = ++loadSeq
  loading.value = true
  try {
    const data = await topologyApi.get({
      siteId: siteFilter.value || null,
      roomId: roomFilter.value || null,
      vlanId: vlanFilter.value || null,
      includeDevices: showDevices.value,
    })
    if (seq !== loadSeq) return
    graph.value = data
    // A node that dropped out of the new payload cannot stay selected.
    if (selectedId.value && !elementById.value.has(selectedId.value)) {
      selectedId.value = null
    }
  } catch (err) {
    if (seq !== loadSeq) return
    toastError(describe(err))
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

async function loadReference() {
  try {
    // The backend caps page_size, so `fetchAllPages` loops until the whole
    // list is in memory — a deployment with more rooms than one page still
    // gets a complete filter dropdown instead of a silently truncated one.
    const [sts, rms, vls, sws] = await Promise.all([
      fetchAllPages((p) => sitesApi.list(p)),
      fetchAllPages((p) => roomsApi.list(p)),
      fetchAllPages((p) => vlansApi.list(p)),
      fetchAllPages((p) => switchesApi.list(p)),
    ])
    sites.value = sts
    rooms.value = rms
    vlans.value = vls
    switches.value = sws
  } catch (err) {
    toastError(describe(err))
  }
}

onMounted(async () => {
  // The AI probe is independent: a 403/404 there must not stop the graph from
  // loading, so it resolves on its own and only hides a button on failure.
  aiApi
    .status()
    .then((s) => {
      aiStatus.value = s
    })
    .catch(() => {
      aiStatus.value = null
    })
  await Promise.all([loadReference(), loadGraph()])
})

// Changing the site clears a now-inconsistent room selection before the
// refetch, so the two filters can never disagree.
watch(siteFilter, () => {
  const room = rooms.value.find((r) => r.id === roomFilter.value)
  if (room && siteFilter.value && room.site_id !== siteFilter.value) {
    roomFilter.value = 0
  }
  loadGraph()
})
watch([roomFilter, vlanFilter, showDevices], () => loadGraph())

// ---------------------------------------------------------------------------
// Derived
// ---------------------------------------------------------------------------

const nodes = computed<TopologyNodeData[]>(() => (graph.value?.nodes ?? []).map((x) => x.data))
const edges = computed<TopologyEdgeData[]>(() => (graph.value?.edges ?? []).map((x) => x.data))
// Every count is required on the wire; this only covers the pre-first-load
// window where there is no payload yet.
const EMPTY_STATS: TopologyStats = {
  sites: 0,
  rooms: 0,
  switches: 0,
  devices: 0,
  links: 0,
  attachments: 0,
  isolated_switches: 0,
  unplaced_nodes: 0,
  link_types: {},
}
const stats = computed<TopologyStats>(() => graph.value?.stats ?? EMPTY_STATS)

const nodeById = computed(() => new Map(nodes.value.map((nd) => [nd.id, nd])))
const edgeById = computed(() => new Map(edges.value.map((ed) => [ed.id, ed])))
const elementById = computed(() => {
  const map = new Map<string, TopologyNodeData | TopologyEdgeData>()
  for (const [id, nd] of nodeById.value) map.set(id, nd)
  for (const [id, ed] of edgeById.value) map.set(id, ed)
  return map
})

/** Leaf nodes only — nobody wants the group boxes as table rows. */
const leafNodes = computed(() =>
  nodes.value.filter((nd) => nd.kind === 'switch' || nd.kind === 'device'),
)

const isEmpty = computed(() => !loading.value && leafNodes.value.length === 0)

const selectedNode = computed(() =>
  selectedId.value ? (nodeById.value.get(selectedId.value) ?? null) : null,
)
const selectedEdge = computed(() =>
  selectedId.value ? (edgeById.value.get(selectedId.value) ?? null) : null,
)
const hasSelection = computed(() => !!(selectedNode.value || selectedEdge.value))

/** Every edge touching the selected node, for the inspector's neighbour list. */
const selectedNeighbours = computed(() => {
  const nd = selectedNode.value
  if (!nd) return []
  return edges.value
    .filter((ed) => ed.source === nd.id || ed.target === nd.id)
    .map((ed) => ({
      edge: ed,
      other: nodeById.value.get(ed.source === nd.id ? ed.target : ed.source) ?? null,
    }))
})

/** "SITE / ROOM" — a bare room code is ambiguous across sites. */
function groupLabel(node: TopologyNodeData): string | null {
  if (!node.parent) return null
  const room = nodeById.value.get(node.parent)
  if (!room) return null
  const site = room.parent ? nodeById.value.get(room.parent) : null
  return site ? `${site.label} / ${room.label}` : room.label
}

function portUtilisation(node: TopologyNodeData): number | null {
  if (!node.ports_total) return null
  return Math.round(((node.ports_used ?? 0) / node.ports_total) * 100)
}

function nodeLabelOf(id: string): string {
  return nodeById.value.get(id)?.label ?? id
}

function formatSpeed(mbps: number | null | undefined): string {
  if (!mbps) return '—'
  return mbps >= 1000 ? `${n(mbps / 1000)} Gb/s` : `${n(mbps)} Mb/s`
}

const edgeCountByNode = computed(() => {
  const counts = new Map<string, number>()
  for (const ed of edges.value) {
    counts.set(ed.source, (counts.get(ed.source) ?? 0) + 1)
    counts.set(ed.target, (counts.get(ed.target) ?? 0) + 1)
  }
  return counts
})

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

const siteOptions = computed(() => [
  { value: 0, label: t('topology.filters.allSites') },
  ...sites.value.map((s) => ({ value: s.id, label: `${s.code} — ${s.name}` })),
])
const roomOptions = computed(() => [
  { value: 0, label: t('topology.filters.allRooms') },
  ...rooms.value
    .filter((r) => !siteFilter.value || r.site_id === siteFilter.value)
    .map((r) => ({ value: r.id, label: r.code })),
])
const vlanOptions = computed(() => [
  { value: 0, label: t('topology.filters.allVlans') },
  ...vlans.value.map((v) => ({ value: v.id, label: `${v.vlan_id} — ${v.name}` })),
])
const layoutOptions = computed(() =>
  (['dagre', 'cose', 'breadthfirst', 'circle', 'grid'] as LayoutName[]).map((value) => ({
    value,
    label: t(`topology.layouts.${value}`),
  })),
)
const viewModeOptions = computed(() => [
  { value: 'graph' as ViewMode, label: t('topology.view.graph'), icon: LayoutGrid },
  { value: 'list' as ViewMode, label: t('topology.view.list'), icon: ListIcon },
])

const statTiles = computed(() => [
  { key: 'switches', value: stats.value.switches ?? 0, icon: Server },
  { key: 'devices', value: stats.value.devices ?? 0, icon: HardDrive },
  { key: 'links', value: stats.value.links ?? 0, icon: Cable },
  { key: 'sites', value: stats.value.sites ?? 0, icon: Network },
])

// The two counts worth acting on. Rendered only when non-zero: a row of
// zeroes is noise, a row that appears is a finding.
const warnings = computed(() =>
  [
    { key: 'isolated', count: stats.value.isolated_switches ?? 0 },
    { key: 'unplaced', count: stats.value.unplaced_nodes ?? 0 },
  ].filter((w) => w.count > 0),
)

const MEDIA_KINDS = ['copper', 'fiber', 'dac', 'virtual'] as const

// ---------------------------------------------------------------------------
// Selection
// ---------------------------------------------------------------------------

function select(id: string) {
  selectedId.value = id
  if (viewMode.value === 'graph') canvasRef.value?.centerOn(id)
}
function clearSelection() {
  selectedId.value = null
}

/** Open the entity's own page — the graph answers "how", detail pages "what". */
function openEntity(node: TopologyNodeData) {
  if (node.kind === 'switch') {
    router.push({ name: 'switch-detail', params: { id: node.entity_id } })
  } else if (node.kind === 'device') {
    router.push({ name: 'devices', query: { highlight: String(node.entity_id) } })
  } else {
    router.push({
      name: 'settings',
      query: { tab: node.kind === 'site' ? 'sites' : 'rooms', highlight: String(node.entity_id) },
    })
  }
}

function exportPng() {
  const uri = canvasRef.value?.exportPng()
  if (!uri) return
  const a = document.createElement('a')
  a.href = uri
  a.download = 'netforge-topology.png'
  a.click()
}

// ---------------------------------------------------------------------------
// Link editing
// ---------------------------------------------------------------------------

const linkEditorOpen = ref(false)
const editingLink = ref<Link | null>(null)
const linkDeleteConfirmOpen = ref(false)
const deletingLink = ref<TopologyEdgeData | null>(null)
const deleteBusy = ref(false)

/** `link-<id>` on a cable edge; attachments have no Link row behind them. */
function linkIdOf(edge: TopologyEdgeData): number | null {
  if (edge.kind !== 'link') return null
  const id = Number(edge.id.slice('link-'.length))
  return Number.isFinite(id) ? id : null
}

function openNewLink() {
  editingLink.value = null
  linkEditorOpen.value = true
}

async function openEditLink(edge: TopologyEdgeData) {
  const id = linkIdOf(edge)
  if (id === null) return
  try {
    // The graph payload carries render data, not the full Link row the editor
    // needs (endpoints, description) — fetch it rather than reconstruct it.
    editingLink.value = await linksApi.get(id)
    linkEditorOpen.value = true
  } catch (err) {
    toastError(describe(err))
  }
}

function askDeleteLink(edge: TopologyEdgeData) {
  if (linkIdOf(edge) === null) return
  deletingLink.value = edge
  linkDeleteConfirmOpen.value = true
}

async function deleteLink() {
  const edge = deletingLink.value
  const id = edge ? linkIdOf(edge) : null
  if (id === null) return
  deleteBusy.value = true
  try {
    await linksApi.delete(id)
    toastSuccess(t('link.deletedToast'))
    if (selectedId.value === edge!.id) clearSelection()
    await loadGraph()
  } catch (err) {
    toastError(describe(err))
  } finally {
    deleteBusy.value = false
    linkDeleteConfirmOpen.value = false
    deletingLink.value = null
  }
}

// A named handler rather than an inlined multi-statement `@close` — the Vue
// template parser trips on `a = 1\nb = null` inside an attribute (see the
// same note in SettingsView).
function closeLinkEditor() {
  linkEditorOpen.value = false
  editingLink.value = null
}

async function onLinkSaved() {
  linkEditorOpen.value = false
  editingLink.value = null
  await loadGraph()
}

// ---------------------------------------------------------------------------
// List-mode tables
// ---------------------------------------------------------------------------

const nodeColumns = computed<DataTableColumn<TopologyNodeData>[]>(() => [
  { key: 'label', label: t('topology.table.name') },
  { key: 'kind', label: t('topology.table.kind') },
  { key: 'group', label: t('topology.table.location'), hideOnSm: true },
  { key: 'ports', label: t('topology.table.ports'), hideOnSm: true },
  { key: 'links', label: t('topology.table.connections') },
])

const edgeColumns = computed<DataTableColumn<TopologyEdgeData>[]>(() => [
  { key: 'endpoints', label: t('topology.table.endpoints') },
  { key: 'kind', label: t('topology.table.kind') },
  { key: 'link_type', label: t('topology.table.media'), hideOnSm: true },
  { key: 'speed_mbps', label: t('topology.table.speed'), hideOnSm: true },
  { key: 'actions', label: '' },
])

function rowRing(id: string): string {
  return id === selectedId.value ? 'ring-2 ring-inset ring-primary-500' : ''
}
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1600px] mx-auto nf-stagger">
    <PageHeader :title="t('nav.topology')" :subtitle="t('topology.subtitle')">
      <template #actions>
        <Button v-if="aiStatus?.enabled && isAdmin" variant="secondary" @click="aiModalOpen = true">
          <Sparkles class="w-4 h-4" :stroke-width="1.9" aria-hidden="true" />
          {{ t('topology.suggestLinks') }}
        </Button>
        <Button v-if="isAdmin" variant="primary" @click="openNewLink">
          <Plus class="w-4 h-4" :stroke-width="1.9" aria-hidden="true" />
          {{ t('link.new') }}
        </Button>
      </template>
    </PageHeader>

    <!-- Counts describe the payload on screen, truncation included. -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6">
      <div v-for="tile in statTiles" :key="tile.key" class="nf-card px-4 py-3">
        <span class="nf-legend flex items-center gap-1.5">
          <component :is="tile.icon" class="w-3 h-3" :stroke-width="2" aria-hidden="true" />
          {{ t(`topology.stats.${tile.key}`) }}
        </span>
        <span class="block text-2xl font-semibold text-fg tabular-nums mt-1">
          {{ n(tile.value) }}
        </span>
      </div>
    </div>

    <div v-if="warnings.length || graph?.truncated" class="flex flex-wrap gap-2 mt-3">
      <Badge v-for="w in warnings" :key="w.key" tone="warning" size="md">
        {{ t(`topology.warnings.${w.key}`, w.count) }}
      </Badge>
      <Badge v-if="graph?.truncated" tone="warning" size="md">
        <TriangleAlert class="w-3.5 h-3.5" :stroke-width="2" aria-hidden="true" />
        {{ t('topology.truncatedNotice') }}
      </Badge>
    </div>

    <!-- Filters are server-side, so each change is one request. -->
    <div class="nf-card p-4 mt-6 flex flex-wrap items-end gap-4">
      <label class="flex flex-col gap-1.5 min-w-[13rem]">
        <span class="nf-legend">{{ t('site.label') }}</span>
        <Select v-model="siteFilter" :options="siteOptions" :aria-label="t('site.label')" />
      </label>
      <label class="flex flex-col gap-1.5 min-w-[11rem]">
        <span class="nf-legend">{{ t('room.label') }}</span>
        <Select v-model="roomFilter" :options="roomOptions" :aria-label="t('room.label')" />
      </label>
      <label class="flex flex-col gap-1.5 min-w-[13rem]">
        <span class="nf-legend">{{ t('vlan.label') }}</span>
        <Select v-model="vlanFilter" :options="vlanOptions" :aria-label="t('vlan.label')" />
      </label>
      <label class="flex items-center gap-2 h-9 select-none cursor-pointer text-fg">
        <input
          v-model="showDevices"
          type="checkbox"
          class="h-4 w-4 rounded accent-primary-600 cursor-pointer"
        />
        <span class="text-sm">{{ t('topology.filters.showDevices') }}</span>
      </label>

      <div class="ms-auto flex items-end gap-3">
        <label v-if="viewMode === 'graph'" class="flex flex-col gap-1.5 min-w-[10rem]">
          <span class="nf-legend">{{ t('topology.layout') }}</span>
          <Select v-model="layout" :options="layoutOptions" :aria-label="t('topology.layout')" />
        </label>
        <Segmented
          v-model="viewMode"
          :options="viewModeOptions"
          :aria-label="t('topology.view.label')"
        />
      </div>
    </div>

    <!-- Skeleton on first load only. A filter change keeps the previous graph
         on screen so the page does not blink between two similar views. -->
    <div v-if="loading && !graph" class="mt-6 grid lg:grid-cols-[1fr_22rem] gap-6">
      <Skeleton class="h-[34rem] rounded-lg" />
      <Skeleton class="h-[34rem] rounded-lg hidden lg:block" />
    </div>

    <EmptyState
      v-else-if="isEmpty"
      class="mt-6"
      :icon="Network"
      :title="t('topology.empty.title')"
      :description="t('topology.empty.body')"
    >
      <template #action>
        <Button variant="primary" @click="router.push({ name: 'switches' })">
          {{ t('topology.empty.cta') }}
        </Button>
      </template>
    </EmptyState>

    <div v-else class="mt-6 grid lg:grid-cols-[1fr_22rem] gap-6 items-start">
      <!-- ------------------------------ Graph ------------------------------ -->
      <div v-if="viewMode === 'graph'" class="relative min-w-0">
        <div class="h-[34rem]">
          <TopologyCanvas
            ref="canvasRef"
            :nodes="graph!.nodes"
            :edges="graph!.edges"
            :layout="layout"
            :selected-id="selectedId"
            @select-node="select"
            @select-edge="select"
            @select-clear="clearSelection"
          />
        </div>

        <div class="absolute top-3 end-3 flex gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            :title="t('topology.fit')"
            :aria-label="t('topology.fit')"
            @click="canvasRef?.fit()"
          >
            <Maximize class="w-4 h-4" :stroke-width="1.9" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :title="t('topology.relayout')"
            :aria-label="t('topology.relayout')"
            @click="canvasRef?.relayout()"
          >
            <RotateCcw class="w-4 h-4" :stroke-width="1.9" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :title="t('topology.exportPng')"
            :aria-label="t('topology.exportPng')"
            @click="exportPng"
          >
            <Download class="w-4 h-4" :stroke-width="1.9" aria-hidden="true" />
          </Button>
        </div>

        <!-- Permanent legend. Line style and outline carry meaning; a key that
             only appears on selection loses the meaning exactly when someone
             is scanning the whole graph. -->
        <div
          class="absolute bottom-3 start-3 nf-card px-3 py-2.5 flex flex-col gap-1.5 bg-surface/95 backdrop-blur-sm"
        >
          <span class="nf-legend">{{ t('topology.legend.title') }}</span>
          <span
            v-for="media in MEDIA_KINDS"
            :key="media"
            class="flex items-center gap-2 text-xs text-fg-muted"
          >
            <svg width="22" height="6" aria-hidden="true" class="flex-shrink-0">
              <line
                x1="0"
                y1="3"
                x2="22"
                y2="3"
                stroke="currentColor"
                :stroke-width="media === 'fiber' ? 3 : 1.5"
                :stroke-dasharray="
                  media === 'dac' ? '5 3' : media === 'virtual' ? '2 3' : undefined
                "
              />
            </svg>
            {{ t(`link.types.${media}`) }}
          </span>
          <span class="flex items-center gap-2 text-xs text-fg-muted">
            <svg width="22" height="10" aria-hidden="true" class="flex-shrink-0">
              <rect
                x="0.75"
                y="1"
                width="20.5"
                height="8"
                rx="2"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-dasharray="3 2"
              />
            </svg>
            {{ t('topology.legend.isolated') }}
          </span>
        </div>
      </div>

      <!-- ------------------------------ List ------------------------------- -->
      <div v-else class="flex flex-col gap-6 min-w-0">
        <section>
          <h2 class="nf-legend mb-2">
            {{ t('topology.table.nodesHeading') }} ({{ n(leafNodes.length) }})
          </h2>
          <DataTable
            :columns="nodeColumns"
            :rows="leafNodes"
            clickable
            :row-class="(row) => rowRing(row.id)"
            @row-click="(row) => select(row.id)"
          >
            <template #cell-label="{ row }">
              <span class="font-medium text-fg">{{ row.label }}</span>
            </template>
            <template #cell-kind="{ row }">
              <Badge :tone="row.kind === 'switch' ? 'primary' : 'neutral'">
                {{ t(`topology.kinds.${row.kind}`) }}
              </Badge>
            </template>
            <template #cell-group="{ row }">
              <span class="text-fg-muted">
                {{ groupLabel(row) ?? t('topology.table.unplaced') }}
              </span>
            </template>
            <template #cell-ports="{ row }">
              <span v-if="row.ports_total" class="tabular-nums text-fg-muted">
                {{ row.ports_used ?? 0 }} / {{ row.ports_total }}
              </span>
              <span v-else class="text-fg-subtle">—</span>
            </template>
            <template #cell-links="{ row }">
              <span class="tabular-nums text-fg-muted">
                {{ edgeCountByNode.get(row.id) ?? 0 }}
              </span>
            </template>
          </DataTable>
        </section>

        <section>
          <h2 class="nf-legend mb-2">
            {{ t('topology.table.edgesHeading') }} ({{ n(edges.length) }})
          </h2>
          <DataTable
            :columns="edgeColumns"
            :rows="edges"
            clickable
            :row-class="(row) => rowRing(row.id)"
            @row-click="(row) => select(row.id)"
          >
            <template #cell-endpoints="{ row }">
              <span class="text-fg">
                {{ nodeLabelOf(row.source) }}
                <span v-if="row.port_a" class="text-fg-subtle font-mono text-xs">
                  :{{ row.port_a }}
                </span>
                <span class="text-fg-subtle mx-1" aria-hidden="true">↔</span>
                {{ nodeLabelOf(row.target) }}
                <span v-if="row.port_b" class="text-fg-subtle font-mono text-xs">
                  :{{ row.port_b }}
                </span>
              </span>
            </template>
            <template #cell-kind="{ row }">
              <Badge :tone="row.kind === 'link' ? 'primary' : 'neutral'">
                {{ t(`topology.edgeKinds.${row.kind}`) }}
              </Badge>
            </template>
            <template #cell-link_type="{ row }">
              <span class="text-fg-muted">
                {{ row.link_type ? t(`link.types.${row.link_type}`) : '—' }}
              </span>
            </template>
            <template #cell-speed_mbps="{ row }">
              <span class="tabular-nums text-fg-muted">{{ formatSpeed(row.speed_mbps) }}</span>
            </template>
            <template #cell-actions="{ row }">
              <div v-if="isAdmin && row.kind === 'link'" class="flex justify-end gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  :aria-label="t('common.edit')"
                  @click.stop="openEditLink(row)"
                >
                  <Pencil class="w-3.5 h-3.5" :stroke-width="1.9" aria-hidden="true" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  :aria-label="t('common.delete')"
                  @click.stop="askDeleteLink(row)"
                >
                  <Trash2 class="w-3.5 h-3.5" :stroke-width="1.9" aria-hidden="true" />
                </Button>
              </div>
            </template>
          </DataTable>
        </section>
      </div>

      <!-- ---------------------------- Inspector ---------------------------- -->
      <!-- Named so it is a distinct landmark from the app sidebar — screen
           readers list both, and "complementary" twice with no name is a
           coin toss for whoever is trying to reach the details panel. -->
      <aside
        class="nf-card p-5 lg:sticky lg:top-6"
        aria-live="polite"
        :aria-label="t('topology.inspector.region')"
      >
        <div v-if="!hasSelection" class="text-center py-8">
          <Network class="w-5 h-5 text-fg-subtle mx-auto" :stroke-width="1.75" aria-hidden="true" />
          <p class="nf-legend mt-3">{{ t('topology.inspector.title') }}</p>
          <p class="text-sm text-fg-muted mt-2">{{ t('topology.inspector.hint') }}</p>
        </div>

        <template v-else>
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <span class="nf-legend">
                {{
                  selectedNode
                    ? t(`topology.kinds.${selectedNode.kind}`)
                    : t(`topology.edgeKinds.${selectedEdge!.kind}`)
                }}
              </span>
              <p class="text-lg font-semibold text-fg mt-1 truncate">
                {{
                  selectedNode
                    ? selectedNode.label
                    : `${nodeLabelOf(selectedEdge!.source)} ↔ ${nodeLabelOf(selectedEdge!.target)}`
                }}
              </p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              :aria-label="t('common.close')"
              @click="clearSelection"
            >
              <XIcon class="w-4 h-4" :stroke-width="1.9" aria-hidden="true" />
            </Button>
          </div>

          <template v-if="selectedNode">
            <dl class="mt-4 flex flex-col gap-2.5 text-sm">
              <div v-if="groupLabel(selectedNode)" class="flex justify-between gap-3">
                <dt class="text-fg-muted">{{ t('topology.table.location') }}</dt>
                <dd class="text-fg text-end">{{ groupLabel(selectedNode) }}</dd>
              </div>
              <div v-if="selectedNode.vendor" class="flex justify-between gap-3">
                <dt class="text-fg-muted">{{ t('switch.fields.vendor') }}</dt>
                <dd class="text-fg text-end">
                  {{ selectedNode.vendor }}{{ selectedNode.model ? ` ${selectedNode.model}` : '' }}
                </dd>
              </div>
              <div v-if="selectedNode.management_ip" class="flex justify-between gap-3">
                <dt class="text-fg-muted">{{ t('switch.fields.managementIp') }}</dt>
                <dd class="text-fg text-end font-mono text-xs">
                  {{ selectedNode.management_ip }}
                </dd>
              </div>
              <div v-if="selectedNode.device_type" class="flex justify-between gap-3">
                <dt class="text-fg-muted">{{ t('device.fields.type') }}</dt>
                <dd class="text-fg text-end">
                  {{ t(`device.types.${selectedNode.device_type}`) }}
                </dd>
              </div>
            </dl>

            <!-- Port utilisation: the number that decides whether this switch
                 can take another drop. -->
            <div v-if="portUtilisation(selectedNode) !== null" class="mt-4">
              <div class="flex items-baseline justify-between">
                <span class="nf-legend">{{ t('topology.table.ports') }}</span>
                <span class="text-sm tabular-nums text-fg">
                  {{ selectedNode.ports_used ?? 0 }} / {{ selectedNode.ports_total }}
                </span>
              </div>
              <div
                class="h-1.5 rounded-full bg-border mt-2 overflow-hidden"
                role="meter"
                :aria-valuenow="portUtilisation(selectedNode) ?? 0"
                :aria-valuemin="0"
                :aria-valuemax="100"
                :aria-label="t('topology.table.ports')"
              >
                <div
                  class="h-full bg-primary-500 rounded-full transition-all duration-300"
                  :style="{ width: `${portUtilisation(selectedNode)}%` }"
                />
              </div>
            </div>

            <div class="mt-5">
              <span class="nf-legend">
                {{ t('topology.inspector.neighbours') }} ({{ n(selectedNeighbours.length) }})
              </span>
              <ul v-if="selectedNeighbours.length" class="mt-2 flex flex-col gap-1">
                <li v-for="hop in selectedNeighbours" :key="hop.edge.id">
                  <button
                    type="button"
                    class="w-full text-start nf-interactive rounded-md px-2 py-1.5 flex items-center justify-between gap-2"
                    :disabled="!hop.other"
                    @click="hop.other && select(hop.other.id)"
                  >
                    <span class="text-sm text-fg truncate">{{ hop.other?.label ?? '—' }}</span>
                    <span class="text-xs font-mono text-fg-subtle flex-shrink-0">
                      {{
                        hop.edge.link_type
                          ? t(`link.types.${hop.edge.link_type}`)
                          : t('topology.edgeKinds.attachment')
                      }}
                    </span>
                  </button>
                </li>
              </ul>
              <p v-else class="text-sm text-fg-muted mt-2">
                {{ t('topology.inspector.noNeighbours') }}
              </p>
            </div>

            <Button variant="secondary" class="w-full mt-5" @click="openEntity(selectedNode)">
              {{ t('topology.inspector.open') }}
            </Button>
          </template>

          <template v-else-if="selectedEdge">
            <dl class="mt-4 flex flex-col gap-2.5 text-sm">
              <div class="flex justify-between gap-3">
                <dt class="text-fg-muted">{{ t('topology.table.media') }}</dt>
                <dd class="text-fg text-end">
                  {{ selectedEdge.link_type ? t(`link.types.${selectedEdge.link_type}`) : '—' }}
                </dd>
              </div>
              <div class="flex justify-between gap-3">
                <dt class="text-fg-muted">{{ t('topology.table.speed') }}</dt>
                <dd class="text-fg text-end tabular-nums">
                  {{ formatSpeed(selectedEdge.speed_mbps) }}
                </dd>
              </div>
              <div v-if="selectedEdge.port_a" class="flex justify-between gap-3">
                <dt class="text-fg-muted">{{ nodeLabelOf(selectedEdge.source) }}</dt>
                <dd class="text-fg text-end font-mono text-xs">
                  {{ selectedEdge.port_a_label || `#${selectedEdge.port_a}` }}
                </dd>
              </div>
              <div v-if="selectedEdge.port_b" class="flex justify-between gap-3">
                <dt class="text-fg-muted">{{ nodeLabelOf(selectedEdge.target) }}</dt>
                <dd class="text-fg text-end font-mono text-xs">
                  {{ selectedEdge.port_b_label || `#${selectedEdge.port_b}` }}
                </dd>
              </div>
            </dl>

            <div v-if="isAdmin && selectedEdge.kind === 'link'" class="flex gap-2 mt-5">
              <Button variant="secondary" class="flex-1" @click="openEditLink(selectedEdge)">
                <Pencil class="w-3.5 h-3.5" :stroke-width="1.9" aria-hidden="true" />
                {{ t('common.edit') }}
              </Button>
              <Button variant="danger" class="flex-1" @click="askDeleteLink(selectedEdge)">
                <Trash2 class="w-3.5 h-3.5" :stroke-width="1.9" aria-hidden="true" />
                {{ t('common.delete') }}
              </Button>
            </div>
          </template>
        </template>
      </aside>
    </div>

    <LinkEditor
      :open="linkEditorOpen"
      :link="editingLink"
      :switches="switches"
      @close="closeLinkEditor"
      @saved="onLinkSaved"
    />

    <LinkSuggestionsModal :open="aiModalOpen" @close="aiModalOpen = false" @accepted="loadGraph" />

    <ConfirmDialog
      :open="linkDeleteConfirmOpen"
      :title="t('link.edit')"
      :message="t('link.deleteConfirm')"
      :confirm-label="t('common.delete')"
      variant="danger"
      :loading="deleteBusy"
      @confirm="deleteLink"
      @cancel="linkDeleteConfirmOpen = false"
    />
  </div>
</template>
