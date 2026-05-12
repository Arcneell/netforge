<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowRight,
  Download,
  Layers,
  Maximize,
  Pencil,
  Plus,
  RotateCcw,
  Trash2,
  X as XIcon,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import Select from '@/components/ui/Select.vue'
import Badge from '@/components/ui/Badge.vue'
import Spinner from '@/components/ui/Spinner.vue'
import EmptyState from '@/components/EmptyState.vue'
import TopologyCanvas, { type LayoutName } from '@/components/TopologyCanvas.vue'
import LinkEditor from '@/components/editors/LinkEditor.vue'
import { linksApi, roomsApi, sitesApi, switchesApi, topologyApi } from '@/api'
import type { Link, Room, Site, Switch, TopologyEdge, TopologyNode } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'
import { useAuth } from '@/composables/useAuth'

const { t } = useI18n()
const router = useRouter()
const { describe } = useApiErrorMessage()
const { error: toastError, success: toastSuccess } = useToast()
const { isAdmin } = useAuth()

const allNodes = ref<TopologyNode[]>([])
const allEdges = ref<TopologyEdge[]>([])
const switchesById = ref<Map<number, Switch>>(new Map())
const roomsById = ref<Map<number, Room>>(new Map())
const sites = ref<Site[]>([])
const loading = ref(true)

const layout = ref<LayoutName>('dagre')
const siteFilter = ref<number | 0>(0) // 0 = all sites
const selectedNodeId = ref<string | null>(null)
const selectedEdgeId = ref<string | null>(null)

const canvasRef = ref<InstanceType<typeof TopologyCanvas> | null>(null)

async function load() {
  loading.value = true
  try {
    // Parallel: graph + switch metadata for the side panel + sites/rooms for filtering.
    // The /api/topology payload alone doesn't include the site_id (only room_id),
    // so we resolve the site via rooms[room_id].site_id.
    // Backend caps `page_size` at 200 (rejects >200 with 422). For v1 that's
    // larger than any realistic switch/room inventory; if a single site ever
    // outgrows 200 we'll add pagination here.
    const [topo, sw, rms, sts] = await Promise.all([
      topologyApi.get(),
      switchesApi.list({ page_size: 200 }),
      roomsApi.list({ page_size: 200 }),
      sitesApi.list({ page_size: 200 }),
    ])
    allNodes.value = topo.nodes
    allEdges.value = topo.edges
    switchesById.value = new Map(sw.items.map((s) => [s.id, s]))
    roomsById.value = new Map(rms.items.map((r) => [r.id, r]))
    sites.value = sts.items
  } catch (err) {
    // Don't swallow — without a toast the user sees the empty state with no
    // hint that the load failed. console.error keeps a hard trace for devtools.
    console.error('Failed to load topology', err)
    toastError(describe(err))
  } finally {
    loading.value = false
  }
}

onMounted(load)

// Filter the graph by site. Node ids look like "switch-<id>"; we resolve the
// switch -> room -> site chain. Edges are kept only when both endpoints survive.
const filteredNodes = computed<TopologyNode[]>(() => {
  if (!siteFilter.value) return allNodes.value
  return allNodes.value.filter((n) => {
    const roomId = n.data.room_id
    if (!roomId) return false
    const room = roomsById.value.get(roomId)
    return room?.site_id === siteFilter.value
  })
})

const filteredEdges = computed<TopologyEdge[]>(() => {
  if (!siteFilter.value) return allEdges.value
  const keepIds = new Set(filteredNodes.value.map((n) => n.data.id))
  return allEdges.value.filter((e) => keepIds.has(e.data.source) && keepIds.has(e.data.target))
})

const isEmpty = computed(() => !loading.value && filteredNodes.value.length === 0)

const layoutOptions = computed(() => [
  { value: 'dagre', label: t('topology.layouts.dagre') },
  { value: 'cose', label: t('topology.layouts.cose') },
  { value: 'breadthfirst', label: t('topology.layouts.breadthfirst') },
  { value: 'circle', label: t('topology.layouts.circle') },
  { value: 'grid', label: t('topology.layouts.grid') },
])

const siteOptions = computed(() => [
  { value: 0, label: t('common.all') },
  ...sites.value.map((s) => ({ value: s.id, label: `${s.code} — ${s.name}` })),
])

const selectedNode = computed<TopologyNode | null>(() =>
  selectedNodeId.value
    ? (allNodes.value.find((n) => n.data.id === selectedNodeId.value) ?? null)
    : null,
)

const selectedEdge = computed<TopologyEdge | null>(() =>
  selectedEdgeId.value
    ? (allEdges.value.find((e) => e.data.id === selectedEdgeId.value) ?? null)
    : null,
)

// The node `id` arrives as e.g. "sw-42" (see backend services/topology.py) —
// strip the prefix to recover the numeric Switch.id for routing.
function switchIdFromNodeId(nodeId: string): number | null {
  const m = nodeId.match(/^sw-(\d+)$/)
  return m ? Number(m[1]) : null
}

function onSelectNode(id: string) {
  selectedNodeId.value = id
  selectedEdgeId.value = null
}
function onSelectEdge(id: string) {
  selectedEdgeId.value = id
  selectedNodeId.value = null
}
function onSelectClear() {
  selectedNodeId.value = null
  selectedEdgeId.value = null
}

function openSwitch(nodeId: string) {
  const id = switchIdFromNodeId(nodeId)
  if (id !== null) router.push(`/switches/${id}`)
}

function exportPng() {
  const dataUrl = canvasRef.value?.exportPng()
  if (!dataUrl) return
  // Anchor download — keeps everything client-side, no server round-trip.
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = `topology-${new Date().toISOString().slice(0, 10)}.png`
  document.body.appendChild(a)
  a.click()
  a.remove()
}

const linkTypeTone = {
  copper: 'neutral' as const,
  fiber: 'primary' as const,
  dac: 'warning' as const,
  virtual: 'muted' as const,
}

// --- Link editor wiring --------------------------------------------------- #

const linkEditorOpen = ref(false)
const linkBeingEdited = ref<Link | null>(null)

const switchesList = computed<Switch[]>(() => Array.from(switchesById.value.values()))

function linkIdFromEdgeId(edgeId: string): number | null {
  // Topology edges encode the link id in their cytoscape id: "link-<id>".
  const m = edgeId.match(/^link-(\d+)$/)
  return m ? Number(m[1]) : null
}

function openCreateLink() {
  linkBeingEdited.value = null
  linkEditorOpen.value = true
}

async function openEditLink() {
  const edge = selectedEdge.value
  if (!edge) return
  const id = linkIdFromEdgeId(edge.data.id)
  if (id === null) return
  try {
    // The topology endpoint doesn't return `description`, so we fetch the
    // canonical Link before opening the editor — that way the description
    // round-trips instead of being silently nulled on save.
    linkBeingEdited.value = await linksApi.get(id)
    linkEditorOpen.value = true
  } catch (err) {
    toastError(describe(err))
  }
}

async function confirmDeleteLink() {
  const edge = selectedEdge.value
  if (!edge) return
  const id = linkIdFromEdgeId(edge.data.id)
  if (id === null) return
  if (!window.confirm(t('link.deleteConfirm'))) return
  try {
    await linksApi.delete(id)
    toastSuccess(t('link.deletedToast'))
    onSelectClear()
    await load()
  } catch (err) {
    toastError(describe(err))
  }
}

async function onLinkSaved() {
  // Refresh the graph so the new/updated edge shows up; the edge ids may
  // change on create, so dropping the selection is the simplest valid state.
  onSelectClear()
  await load()
}
</script>

<template>
  <div class="p-6 max-w-[100rem] mx-auto h-full flex flex-col">
    <PageHeader :title="t('nav.topology')" :subtitle="t('topology.subtitle')">
      <template #actions>
        <div class="w-44">
          <Select
            :model-value="siteFilter"
            :options="siteOptions"
            :aria-label="t('site.label')"
            @update:model-value="(v) => (siteFilter = Number(v) as number | 0)"
          />
        </div>
        <div class="w-44">
          <Select
            :model-value="layout"
            :options="layoutOptions"
            :aria-label="t('topology.layout')"
            @update:model-value="(v) => (layout = v as LayoutName)"
          />
        </div>
        <Button variant="secondary" :aria-label="t('topology.fit')" @click="canvasRef?.fit()">
          <Maximize class="w-4 h-4" aria-hidden="true" />
        </Button>
        <Button
          variant="secondary"
          :aria-label="t('topology.relayout')"
          @click="canvasRef?.relayout()"
        >
          <RotateCcw class="w-4 h-4" aria-hidden="true" />
        </Button>
        <Button
          v-if="isAdmin"
          variant="secondary"
          :aria-label="t('link.new')"
          @click="openCreateLink"
        >
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('link.new') }}
        </Button>
        <Button variant="primary" @click="exportPng">
          <Download class="w-4 h-4" aria-hidden="true" />
          {{ t('topology.exportPng') }}
        </Button>
      </template>
    </PageHeader>

    <div class="grid gap-4 flex-1 min-h-0 grid-cols-1 lg:grid-cols-[1fr_22rem]">
      <!-- Canvas -->
      <div class="nf-card overflow-hidden relative flex flex-col min-h-[34rem]">
        <div
          v-if="loading"
          class="absolute inset-0 flex items-center justify-center bg-surface/70 z-10"
        >
          <Spinner :label="t('common.loading')" />
        </div>
        <EmptyState
          v-else-if="isEmpty"
          :icon="Layers"
          :title="t('topology.empty.title')"
          :description="t('topology.empty.description')"
        />
        <TopologyCanvas
          v-else
          ref="canvasRef"
          class="flex-1"
          :nodes="filteredNodes"
          :edges="filteredEdges"
          :layout="layout"
          :selected-id="selectedNodeId ?? selectedEdgeId"
          @select-node="onSelectNode"
          @select-edge="onSelectEdge"
          @select-clear="onSelectClear"
        />
      </div>

      <!-- Side panel: details for the currently selected node or edge -->
      <aside
        class="nf-card p-4 flex flex-col gap-3 lg:max-h-full overflow-y-auto"
        aria-label="Selection details"
      >
        <div v-if="!selectedNode && !selectedEdge" class="text-sm text-fg-muted">
          {{ t('topology.selectPrompt') }}
        </div>

        <!-- Node panel -->
        <template v-else-if="selectedNode">
          <header class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="text-[10px] uppercase tracking-wide text-fg-muted">
                {{ t('switch.label') }}
              </p>
              <h2 class="text-base font-semibold tracking-tight truncate">
                {{ selectedNode.data.label }}
              </h2>
            </div>
            <button
              type="button"
              class="p-1 rounded hover:bg-surface-hover text-fg-muted"
              :aria-label="t('common.close')"
              @click="onSelectClear"
            >
              <XIcon class="w-4 h-4" />
            </button>
          </header>

          <dl class="grid grid-cols-2 gap-2 text-xs">
            <div>
              <dt class="text-fg-muted">{{ t('switch.fields.vendor') }}</dt>
              <dd class="text-fg">{{ selectedNode.data.vendor || '—' }}</dd>
            </div>
            <div>
              <dt class="text-fg-muted">{{ t('switch.fields.model') }}</dt>
              <dd class="text-fg">{{ selectedNode.data.model || '—' }}</dd>
            </div>
            <div class="col-span-2">
              <dt class="text-fg-muted">{{ t('switch.fields.managementIp') }}</dt>
              <dd class="text-fg font-mono">{{ selectedNode.data.management_ip || '—' }}</dd>
            </div>
            <div>
              <dt class="text-fg-muted">{{ t('switch.fields.portCount') }}</dt>
              <dd class="text-fg font-mono">{{ selectedNode.data.ports_total }}</dd>
            </div>
            <div>
              <dt class="text-fg-muted">{{ t('switch.fields.room') }}</dt>
              <dd class="text-fg font-mono">
                {{
                  selectedNode.data.room_id
                    ? (roomsById.get(selectedNode.data.room_id)?.code ??
                      `#${selectedNode.data.room_id}`)
                    : '—'
                }}
              </dd>
            </div>
          </dl>

          <Button
            variant="secondary"
            size="sm"
            class="mt-2"
            @click="openSwitch(selectedNode.data.id)"
          >
            {{ t('topology.openSwitch') }}
            <ArrowRight class="w-4 h-4" aria-hidden="true" />
          </Button>
        </template>

        <!-- Edge panel -->
        <template v-else-if="selectedEdge">
          <header class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="text-[10px] uppercase tracking-wide text-fg-muted">
                {{ t('topology.link') }}
              </p>
              <h2 class="text-base font-semibold tracking-tight truncate">
                {{
                  switchesById.get(switchIdFromNodeId(selectedEdge.data.source) ?? -1)?.name ??
                  selectedEdge.data.source
                }}
                ↔
                {{
                  switchesById.get(switchIdFromNodeId(selectedEdge.data.target) ?? -1)?.name ??
                  selectedEdge.data.target
                }}
              </h2>
            </div>
            <button
              type="button"
              class="p-1 rounded hover:bg-surface-hover text-fg-muted"
              :aria-label="t('common.close')"
              @click="onSelectClear"
            >
              <XIcon class="w-4 h-4" />
            </button>
          </header>

          <dl class="grid grid-cols-2 gap-2 text-xs">
            <div>
              <dt class="text-fg-muted">{{ t('link.fields.type') }}</dt>
              <dd>
                <Badge
                  :tone="
                    linkTypeTone[selectedEdge.data.link_type as keyof typeof linkTypeTone] ??
                    'neutral'
                  "
                >
                  {{ t(`link.types.${selectedEdge.data.link_type}`) }}
                </Badge>
              </dd>
            </div>
            <div>
              <dt class="text-fg-muted">{{ t('link.fields.speed') }}</dt>
              <dd class="text-fg font-mono">
                {{ selectedEdge.data.speed_mbps ? `${selectedEdge.data.speed_mbps} Mbps` : '—' }}
              </dd>
            </div>
            <div>
              <dt class="text-fg-muted">{{ t('link.fields.portA') }}</dt>
              <dd class="text-fg font-mono">#{{ selectedEdge.data.port_a }}</dd>
            </div>
            <div>
              <dt class="text-fg-muted">{{ t('link.fields.portB') }}</dt>
              <dd class="text-fg font-mono">#{{ selectedEdge.data.port_b }}</dd>
            </div>
          </dl>

          <div v-if="isAdmin" class="flex flex-wrap gap-2 mt-2">
            <Button variant="secondary" size="sm" @click="openEditLink">
              <Pencil class="w-4 h-4" aria-hidden="true" />
              {{ t('common.edit') }}
            </Button>
            <Button variant="danger" size="sm" @click="confirmDeleteLink">
              <Trash2 class="w-4 h-4" aria-hidden="true" />
              {{ t('common.delete') }}
            </Button>
          </div>
        </template>
      </aside>
    </div>

    <LinkEditor
      :open="linkEditorOpen"
      :link="linkBeingEdited"
      :switches="switchesList"
      @close="linkEditorOpen = false"
      @saved="onLinkSaved"
    />
  </div>
</template>
