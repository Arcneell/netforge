<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Plus, Pencil, Trash2 } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import VlanBadge from '@/components/VlanBadge.vue'
import SubnetEditor from '@/components/editors/SubnetEditor.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { subnetsApi, vlansApi } from '@/api'
import type { Subnet, Vlan } from '@/api'
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

const editorOpen = ref(false)
const editing = ref<Subnet | null>(null)
const deleteTarget = ref<Subnet | null>(null)
const deleting = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await subnetsApi.list({ page: page.value, page_size: pageSize })
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function loadVlans() {
  const res = await vlansApi.list({ page_size: 200 })
  vlansById.value = new Map(res.items.map((v) => [v.id, v]))
}

onMounted(() => {
  load()
  loadVlans()
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
  <div class="p-6 max-w-7xl mx-auto">
    <PageHeader :title="t('subnet.labelPlural')" :subtitle="t('subnet.subtitle')">
      <template #actions>
        <Button v-if="isAdmin" variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('subnet.new') }}
        </Button>
      </template>
    </PageHeader>

    <DataTable
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
