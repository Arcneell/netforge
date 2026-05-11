<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Plus, Pencil, Trash2 } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import SwitchEditor from '@/components/editors/SwitchEditor.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { switchesApi } from '@/api'
import type { Switch } from '@/api'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const { t } = useI18n()
const { isAdmin } = useAuth()
const { success } = useToast()
const { describe } = useApiErrorMessage()
const router = useRouter()

const items = ref<Switch[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)

const editorOpen = ref(false)
const editing = ref<Switch | null>(null)
const deleteTarget = ref<Switch | null>(null)
const deleting = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await switchesApi.list({ page: page.value, page_size: pageSize })
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

onMounted(load)

function onNew() {
  editing.value = null
  editorOpen.value = true
}
function onEdit(s: Switch) {
  editing.value = s
  editorOpen.value = true
}
function onRowClick(s: Switch) {
  router.push(`/switches/${s.id}`)
}
async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await switchesApi.delete(deleteTarget.value.id)
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
  { key: 'name', label: t('switch.fields.name'), cellClass: 'font-medium' },
  { key: 'vendor', label: t('switch.fields.vendor'), hideOnSm: true },
  { key: 'model', label: t('switch.fields.model'), hideOnSm: true },
  { key: 'management_ip', label: t('switch.fields.managementIp'), cellClass: 'font-mono' },
  { key: 'port_count', label: t('switch.fields.portCount'), align: 'right', cellClass: 'w-24' },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
]
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto">
    <PageHeader :title="t('switch.labelPlural')" :subtitle="t('switch.subtitle')">
      <template #actions>
        <Button v-if="isAdmin" variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('switch.new') }}
        </Button>
      </template>
    </PageHeader>

    <DataTable
      :columns="columns"
      :rows="items"
      :loading="loading"
      :empty-title="t('switch.labelPlural')"
      :empty-description="t('switch.empty')"
      clickable
      @row-click="onRowClick"
    >
      <template #cell-vendor="{ row }">
        <span class="text-fg-muted">{{ row.vendor || '—' }}</span>
      </template>
      <template #cell-model="{ row }">
        <span class="text-fg-muted">{{ row.model || '—' }}</span>
      </template>
      <template #cell-management_ip="{ row }">
        <span class="text-fg-muted">{{ row.management_ip || '—' }}</span>
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

    <SwitchEditor
      :open="editorOpen"
      :switch-item="editing"
      @close="editorOpen = false"
      @saved="load"
    />
    <ConfirmDialog
      :open="!!deleteTarget"
      :title="t('common.confirmDelete.title', { label: deleteTarget?.name ?? '' })"
      :message="t('common.confirmDelete.message')"
      variant="danger"
      :loading="deleting"
      @confirm="confirmDelete"
      @cancel="deleteTarget = null"
    />
  </div>
</template>
