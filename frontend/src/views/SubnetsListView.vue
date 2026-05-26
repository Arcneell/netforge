<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowUpFromLine, List, Network, Plus, Pencil, Search, Trash2, X } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import VlanBadge from '@/components/VlanBadge.vue'
import SubnetEditor from '@/components/editors/SubnetEditor.vue'
import SubnetTreeRow from '@/components/SubnetTreeRow.vue'
import SubnetFillBar from '@/components/SubnetFillBar.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { sitesApi, subnetsApi, vlansApi } from '@/api'
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
const { describe } = useApiErrorMessage()
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

const editorOpen = ref(false)
const editing = ref<Subnet | null>(null)
const deleteTarget = ref<Subnet | null>(null)
const deleting = ref(false)

async function load() {
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
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadTree() {
  treeLoading.value = true
  try {
    // Map the chip back to the tree endpoint: undefined / 0 = global.
    // Site + VLAN narrow the result; the backend handles the orphan
    // promotion so filtering by a leaf VLAN still surfaces matches.
    tree.value = await subnetsApi.tree({
      vrf_id: vrfFilter.value && vrfFilter.value > 0 ? vrfFilter.value : 0,
      site_id: siteFilter.value,
      vlan_id: vlanFilter.value,
    })
  } finally {
    treeLoading.value = false
  }
}

async function loadVlans() {
  // VLANs feed two things: the badge lookup map for each subnet row AND
  // the VLAN filter chip. Pull the same page once and share. Pagination
  // is capped at 500 — anyone with more than that is multi-tenant and
  // already paying for an enterprise filter UI (a future PR can switch
  // the chip to an async-search combobox).
  const res = await vlansApi.list({ page_size: 500 })
  vlans.value = res.items
  vlansById.value = new Map(res.items.map((v) => [v.id, v]))
}

async function loadSites() {
  try {
    const res = await sitesApi.list({ page_size: 200 })
    sites.value = res.items
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

function toggleNode(id: number) {
  if (collapsed.value.has(id)) collapsed.value.delete(id)
  else collapsed.value.add(id)
  // Force reactivity — Set mutations don't auto-trigger.
  collapsed.value = new Set(collapsed.value)
}

function openSubnet(id: number) {
  router.push(`/subnets/${id}`)
}

// Drag-and-drop reparenting. The DnD MIME mirrors the constant declared
// inside `SubnetTreeRow.vue` — kept in sync by inspection. If we ever
// add a second drop source we should move it to a shared module.
const DRAG_MIME = 'application/x-netforge-subnet-id'
const rootDropActive = ref(false)
// Element the page actually scrolls inside. AppShell wraps the routed
// view in `<main class="flex-1 overflow-y-auto">`, so that's the node
// whose scrollTop we need to nudge during a drag near the top/bottom
// edge of the viewport.
let scrollContainer: HTMLElement | null = null

/**
 * Native HTML5 drag-and-drop has no built-in autoscroll. When the user
 * picks up a row at the bottom of a long tree, dragging upward toward
 * the root drop zone above the fold simply pegs the cursor at the
 * viewport top and never reveals the target. Run a small RAF loop
 * while a drag is in progress: read the cursor's Y position from the
 * dragover events, and scroll the `main` container whenever the
 * cursor lands inside an EDGE_PX band at either end of the viewport.
 *
 * Speed is proportional to how deep the cursor is in the band, so a
 * cursor pressed against the very edge scrolls fastest. Stops the
 * moment the drag ends or the cursor leaves the band.
 */
const EDGE_PX = 80
const MAX_SCROLL_PER_FRAME = 18
let pointerY = 0
let dragRafId: number | null = null

function startDragAutoScroll() {
  if (dragRafId !== null) return
  if (!scrollContainer) {
    scrollContainer = document.querySelector('main')
  }
  const tick = () => {
    if (!scrollContainer) {
      dragRafId = null
      return
    }
    const rect = scrollContainer.getBoundingClientRect()
    const topGap = pointerY - rect.top
    const bottomGap = rect.bottom - pointerY
    let dy = 0
    if (topGap < EDGE_PX && topGap >= 0) {
      // Closer to the edge = stronger pull. 0..EDGE_PX → MAX..0 scroll up.
      dy = -Math.round(MAX_SCROLL_PER_FRAME * (1 - topGap / EDGE_PX))
    } else if (bottomGap < EDGE_PX && bottomGap >= 0) {
      dy = Math.round(MAX_SCROLL_PER_FRAME * (1 - bottomGap / EDGE_PX))
    }
    if (dy !== 0) scrollContainer.scrollBy(0, dy)
    dragRafId = requestAnimationFrame(tick)
  }
  dragRafId = requestAnimationFrame(tick)
}

function stopDragAutoScroll() {
  if (dragRafId !== null) {
    cancelAnimationFrame(dragRafId)
    dragRafId = null
  }
}

function onTreeDragOver(ev: DragEvent) {
  // Only react to our own drags — `types` is available during dragover
  // even though `getData` isn't. Guards against random text/file drops
  // accidentally triggering the autoscroll RAF.
  if (!ev.dataTransfer?.types.includes(DRAG_MIME)) return
  pointerY = ev.clientY
  startDragAutoScroll()
}

/**
 * Look up the current `parent_subnet_id` of a node in the loaded tree.
 * Used to (1) short-circuit no-op drops (dropping a root onto the root
 * zone again, or onto its current parent), and (2) pick the right
 * toast wording (attach vs detach vs move).
 */
function findCurrentParent(nodes: SubnetTreeNode[], id: number): number | null | undefined {
  for (const n of nodes) {
    if (n.id === id) return n.parent_subnet_id
    const inside = findCurrentParent(n.children, id)
    if (inside !== undefined) return inside
  }
  return undefined
}

async function onReparent(payload: { childId: number; parentId: number | null }) {
  // Short-circuit no-ops so the user doesn't see an "attached" toast
  // for dropping a row exactly where it already lives. Returns
  // `undefined` for nodes we can't find (e.g. drag from a stale tree
  // snapshot) — fall through to the API in that case so the backend
  // decides.
  const currentParent = findCurrentParent(tree.value, payload.childId)
  if (currentParent !== undefined && currentParent === payload.parentId) {
    return
  }
  try {
    await subnetsApi.update(payload.childId, { parent_subnet_id: payload.parentId })
    // Pick the toast wording based on the OUTGOING side of the move so
    // the operator gets accurate feedback. Detach = becoming a root,
    // attach = gaining a parent, move = changing parents.
    if (payload.parentId === null) {
      success(t('subnet.tree.detached'))
    } else if (currentParent === null || currentParent === undefined) {
      success(t('subnet.tree.attached'))
    } else {
      success(t('subnet.tree.moved'))
    }
    // Reload both the tree and the flat list so a follow-up view switch
    // shows fresh data — the parent column on the flat list is not yet
    // rendered, but the cache underneath stays correct.
    loadTree()
    if (viewMode.value === 'list') load()
  } catch (err) {
    void describe(err)
  }
}

function onRootDragOver(ev: DragEvent) {
  if (!ev.dataTransfer || !ev.dataTransfer.types.includes(DRAG_MIME)) return
  ev.preventDefault()
  ev.dataTransfer.dropEffect = 'move'
  rootDropActive.value = true
}

function onRootDrop(ev: DragEvent) {
  rootDropActive.value = false
  if (!ev.dataTransfer) return
  const raw = ev.dataTransfer.getData(DRAG_MIME)
  if (!raw) return
  const childId = Number(raw)
  if (!Number.isFinite(childId)) return
  ev.preventDefault()
  onReparent({ childId, parentId: null })
}

// Global cleanup hooks for the autoscroll RAF AND the root-drop-zone
// highlight: whichever end-of-drag event fires first (drop on a
// target, dragend on the source, even an Escape that aborts the drag)
// cancels the loop and clears the highlight. Listeners are installed
// at the window level because the user may release outside the tree
// (e.g. on the sidebar) and we still want to stop scrolling and stop
// pretending the drop zone is active.
function onAnyDragEnd() {
  stopDragAutoScroll()
  rootDropActive.value = false
}

onMounted(() => {
  load()
  loadVlans()
  loadVrfs()
  loadSites()
  window.addEventListener('dragend', onAnyDragEnd)
  window.addEventListener('drop', onAnyDragEnd)
})

onBeforeUnmount(() => {
  window.removeEventListener('dragend', onAnyDragEnd)
  window.removeEventListener('drop', onAnyDragEnd)
  stopDragAutoScroll()
})

function onNew() {
  editing.value = null
  editorOpen.value = true
}

function onEdit(s: Subnet) {
  editing.value = s
  editorOpen.value = true
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
    void describe(err)
  } finally {
    deleting.value = false
  }
}

const columns: DataTableColumn[] = [
  { key: 'cidr', label: t('subnet.fields.cidr'), cellClass: 'font-mono' },
  { key: 'vlan_id', label: t('subnet.fields.vlan'), cellClass: 'w-40' },
  { key: 'gateway', label: t('subnet.fields.gateway'), hideOnSm: true, cellClass: 'font-mono' },
  { key: 'description', label: t('subnet.fields.description'), hideOnSm: true },
  { key: 'usage', label: t('subnet.fields.usage'), cellClass: 'w-40' },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
]
</script>

<template>
  <div class="p-4 sm:p-6 max-w-7xl mx-auto">
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

    <!-- Toolbar — one row on desktop, wraps gracefully on mobile. Order
         left-to-right is the daily-use frequency: view toggle (rare
         flip), then search (primary affordance), then the scope chips
         that drill down further. The "Clear filters" link only shows
         once any filter is active so the bar stays calm by default. -->
    <div class="flex flex-wrap items-center gap-2 mb-4">
      <div
        class="inline-flex items-center gap-0.5 p-0.5 rounded-md border border-border bg-surface h-9"
        role="tablist"
      >
        <button
          type="button"
          role="tab"
          :aria-selected="viewMode === 'list'"
          :class="[
            'px-3 h-full rounded text-sm font-medium transition inline-flex items-center gap-1.5',
            viewMode === 'list'
              ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
              : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
          ]"
          @click="switchView('list')"
        >
          <List class="w-3.5 h-3.5" aria-hidden="true" />
          {{ t('subnet.viewList') }}
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="viewMode === 'tree'"
          :class="[
            'px-3 h-full rounded text-sm font-medium transition inline-flex items-center gap-1.5',
            viewMode === 'tree'
              ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
              : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
          ]"
          @click="switchView('tree')"
        >
          <Network class="w-3.5 h-3.5" aria-hidden="true" />
          {{ t('subnet.viewTree') }}
        </button>
      </div>

      <!-- Search input — debounced, takes the remaining row width so it's
           the obvious primary affordance. Uses the shared `nf-input`
           styling for visual consistency with the rest of the editors. -->
      <div class="relative flex-1 min-w-[14rem] max-w-sm">
        <Search
          class="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-fg-muted pointer-events-none z-10"
          aria-hidden="true"
        />
        <input
          v-model="searchInput"
          type="search"
          :placeholder="t('subnet.searchPlaceholder')"
          :aria-label="t('subnet.searchPlaceholder')"
          class="nf-input nf-input-control pl-9 pr-9"
          autocomplete="off"
          spellcheck="false"
        />
        <button
          v-if="searchInput"
          type="button"
          class="absolute right-1.5 top-1/2 -translate-y-1/2 inline-flex items-center justify-center w-6 h-6 rounded text-fg-muted hover:bg-surface-hover hover:text-fg"
          :aria-label="t('common.reset')"
          @click="searchInput = ''"
        >
          <X class="w-3.5 h-3.5" aria-hidden="true" />
        </button>
      </div>

      <!-- Scope chips. Native <select> with the shared input styling so
           the visual weight matches the search bar. Each chip is hidden
           when there's nothing to pick from (single-site / no-VLAN
           deployments) instead of rendering an empty dropdown. -->
      <select
        :value="vrfFilter === undefined ? '' : String(vrfFilter)"
        class="nf-input nf-input-control w-auto min-w-[8rem] cursor-pointer"
        :aria-label="t('subnet.vrfFilter')"
        @change="
          (e) => {
            const v = (e.target as HTMLSelectElement).value
            onVrfFilterChange(v === '' ? undefined : Number(v))
          }
        "
      >
        <option value="">
          {{ viewMode === 'list' ? t('subnet.vrfFilterAll') : t('subnet.vrfFilterGlobal') }}
        </option>
        <option value="0">{{ t('subnet.vrfFilterGlobal') }}</option>
        <option v-for="v in vrfs" :key="v.id" :value="v.id">{{ v.name }}</option>
      </select>

      <select
        v-if="sites.length > 0"
        :value="siteFilter === undefined ? '' : String(siteFilter)"
        class="nf-input nf-input-control w-auto min-w-[8rem] cursor-pointer"
        :aria-label="t('subnet.fields.site')"
        @change="
          (e) => {
            const v = (e.target as HTMLSelectElement).value
            onSiteFilterChange(v === '' ? undefined : Number(v))
          }
        "
      >
        <option value="">{{ t('subnet.allSites') }}</option>
        <option v-for="s in sites" :key="s.id" :value="s.id">{{ s.code }}</option>
      </select>

      <select
        v-if="vlans.length > 0"
        :value="vlanFilter === undefined ? '' : String(vlanFilter)"
        class="nf-input nf-input-control w-auto min-w-[8rem] cursor-pointer"
        :aria-label="t('subnet.fields.vlan')"
        @change="
          (e) => {
            const v = (e.target as HTMLSelectElement).value
            onVlanFilterChange(v === '' ? undefined : Number(v))
          }
        "
      >
        <option value="">{{ t('subnet.allVlans') }}</option>
        <option v-for="v in vlans" :key="v.id" :value="v.id">{{ v.vlan_id }} — {{ v.name }}</option>
      </select>

      <Button v-if="hasActiveFilters" variant="ghost" size="sm" @click="clearFilters">
        <X class="w-3.5 h-3.5" aria-hidden="true" />
        {{ t('subnet.clearFilters') }}
      </Button>
    </div>

    <!-- Tree view. The container listens for `dragover` so we can
         autoscroll the `main` element when the cursor approaches the
         viewport edges — native HTML5 DnD has no built-in autoscroll. -->
    <div
      v-if="viewMode === 'tree'"
      class="nf-card overflow-hidden"
      @dragover="onTreeDragOver"
    >
      <div v-if="treeLoading" class="p-6 text-center text-fg-muted text-sm">
        {{ t('common.loading') }}
      </div>
      <div v-else-if="tree.length === 0" class="p-6 text-center text-fg-muted text-sm">
        {{ t('subnet.treeEmpty') }}
      </div>
      <template v-else>
        <!-- Top-level drop zone: drag any node here to detach it from
             its current parent (the move sets `parent_subnet_id = null`).
             Visible only to admins so viewers don't see a drop affordance
             that does nothing. The dashed outline pattern is the
             internet's universal "this is a drop target" cue — operators
             recognise it on first hover. -->
        <div
          v-if="isAdmin"
          :class="[
            'mx-3 mt-3 mb-2 px-4 py-3 rounded-md border border-dashed flex items-center justify-center gap-2 text-xs font-medium transition-colors',
            rootDropActive
              ? 'border-primary-500 bg-primary-500/10 text-primary-700 dark:text-primary-300'
              : 'border-border bg-muted/30 text-fg-muted',
          ]"
          @dragover="onRootDragOver"
          @dragleave="rootDropActive = false"
          @drop="onRootDrop"
        >
          <ArrowUpFromLine class="w-3.5 h-3.5" aria-hidden="true" />
          {{ t('subnet.tree.rootDropHint') }}
        </div>
        <ul class="divide-y divide-border/50">
          <SubnetTreeRow
            v-for="(node, idx) in tree"
            :key="node.id"
            :node="node"
            :collapsed="collapsed"
            :depth="0"
            :is-last="idx === tree.length - 1"
            :vlans-by-id="vlansById"
            :can-reparent="isAdmin"
            @toggle="toggleNode"
            @open="openSubnet"
            @reparent="onReparent"
          />
        </ul>
      </template>
    </div>

    <DataTable
      v-else
      :columns="columns"
      :rows="items"
      :loading="loading"
      :empty-title="t('subnet.labelPlural')"
      :empty-description="t('subnet.empty')"
      clickable
      @row-click="onRowClick"
    >
      <template v-if="isAdmin" #empty-action>
        <Button variant="primary" @click="onNew">
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
      <template #cell-gateway="{ row }">
        <span class="text-fg-muted">{{ row.gateway || '—' }}</span>
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

    <SubnetEditor :open="editorOpen" :subnet="editing" @close="editorOpen = false" @saved="load" />
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
