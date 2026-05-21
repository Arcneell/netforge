<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { List, Network, Plus, Pencil, Trash2 } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import VlanBadge from '@/components/VlanBadge.vue'
import SubnetEditor from '@/components/editors/SubnetEditor.vue'
import SubnetTreeRow from '@/components/SubnetTreeRow.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { subnetsApi, vlansApi } from '@/api'
import type { Subnet, Vlan } from '@/api'
import type { SubnetTreeNode } from '@/api/endpoints/subnets'
import { vrfsApi } from '@/api/endpoints/vrfs'
import type { Vrf } from '@/api/endpoints/vrfs'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { parseCidr } from '@/utils/cidr'

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

const vlansById = ref<Map<number, Vlan>>(new Map())
const vrfs = ref<Vrf[]>([])
// Filter chip values:
//   undefined → show every subnet across all VRFs (default list mode)
//   0         → show only the global-scope subnets (vrf_id IS NULL)
//   N (>0)    → show only the subnets in VRF N
// The tree view re-uses the same filter; it always shows a single scope at
// a time (global by default, or a specific VRF when picked).
const vrfFilter = ref<number | undefined>(undefined)

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
    const scope = vrfFilter.value && vrfFilter.value > 0 ? vrfFilter.value : 0
    tree.value = await subnetsApi.tree(scope)
  } finally {
    treeLoading.value = false
  }
}

async function loadVlans() {
  const res = await vlansApi.list({ page_size: 200 })
  vlansById.value = new Map(res.items.map((v) => [v.id, v]))
}

async function loadVrfs() {
  try {
    vrfs.value = await vrfsApi.list()
  } catch {
    // Non-blocking — UI just hides the picker if the call failed.
    vrfs.value = []
  }
}

function onVrfFilterChange(value: number | undefined) {
  vrfFilter.value = value
  page.value = 1
  if (viewMode.value === 'tree') {
    loadTree()
  } else {
    load()
  }
}

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

onMounted(() => {
  load()
  loadVlans()
  loadVrfs()
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

function totalHosts(cidr: string): string {
  try {
    return parseCidr(cidr).total.toLocaleString()
  } catch {
    return '—'
  }
}

const columns: DataTableColumn[] = [
  { key: 'cidr', label: t('subnet.fields.cidr'), cellClass: 'font-mono' },
  { key: 'vlan_id', label: t('subnet.fields.vlan'), cellClass: 'w-40' },
  { key: 'gateway', label: t('subnet.fields.gateway'), hideOnSm: true, cellClass: 'font-mono' },
  { key: 'description', label: t('subnet.fields.description'), hideOnSm: true },
  { key: 'total', label: t('subnet.fields.total'), align: 'right', cellClass: 'w-24 font-mono' },
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

    <!-- View toggle + VRF filter -->
    <div class="flex flex-wrap items-center gap-3 mb-4">
      <div
        class="inline-flex items-center gap-0.5 p-0.5 rounded-md border border-border bg-surface"
        role="tablist"
      >
        <button
          type="button"
          role="tab"
          :aria-selected="viewMode === 'list'"
          :class="[
            'px-3 h-8 rounded text-sm font-medium transition inline-flex items-center gap-1.5',
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
            'px-3 h-8 rounded text-sm font-medium transition inline-flex items-center gap-1.5',
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

      <label class="text-sm inline-flex items-center gap-2">
        <span class="text-xs uppercase tracking-wider text-fg-muted font-semibold">
          {{ t('subnet.vrfFilter') }}
        </span>
        <select
          :value="vrfFilter === undefined ? '' : String(vrfFilter)"
          class="h-8 px-2 rounded border border-border bg-surface text-sm"
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
      </label>
    </div>

    <!-- Tree view -->
    <div v-if="viewMode === 'tree'" class="nf-card overflow-hidden">
      <div v-if="treeLoading" class="p-6 text-center text-fg-muted text-sm">
        {{ t('common.loading') }}
      </div>
      <div v-else-if="tree.length === 0" class="p-6 text-center text-fg-muted text-sm">
        {{ t('subnet.treeEmpty') }}
      </div>
      <ul v-else class="divide-y divide-border/50">
        <SubnetTreeRow
          v-for="node in tree"
          :key="node.id"
          :node="node"
          :collapsed="collapsed"
          :depth="0"
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
      <template #cell-total="{ row }">{{ totalHosts(row.cidr) }}</template>
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
