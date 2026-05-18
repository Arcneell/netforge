<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Pencil, Trash2 } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import VlanBadge from '@/components/VlanBadge.vue'
import VlanEditor from '@/components/editors/VlanEditor.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { vlansApi } from '@/api'
import type { Vlan } from '@/api'
import { useApi } from '@/composables/useApi'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const { t } = useI18n()
const { isAdmin } = useAuth()
const { success } = useToast()
const { describe } = useApiErrorMessage()
// Reserved for future filter-aware fetches; useApi keeps toast wiring centralised.
useApi()

const items = ref<Vlan[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)

const editorOpen = ref(false)
const editing = ref<Vlan | null>(null)
const deleteTarget = ref<Vlan | null>(null)
const deleting = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await vlansApi.list({ page: page.value, page_size: pageSize })
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

function onEdit(vlan: Vlan) {
  editing.value = vlan
  editorOpen.value = true
}

function onSaved(_vlan: Vlan) {
  load()
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await vlansApi.delete(deleteTarget.value.id)
    success(t('common.success'))
    deleteTarget.value = null
    load()
  } catch (err) {
    // useApi's silent flag wasn't passed, so the global toast already surfaces this —
    // but describe() returns a richer i18n message for known codes.
    void describe(err)
  } finally {
    deleting.value = false
  }
}

const columns: DataTableColumn[] = [
  { key: 'vlan_id', label: t('vlan.fields.vlanId'), cellClass: 'w-32 font-mono' },
  { key: 'name', label: t('vlan.fields.name') },
  { key: 'description', label: t('vlan.fields.description'), hideOnSm: true },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
]
</script>

<template>
  <div class="p-4 sm:p-6 max-w-7xl mx-auto">
    <PageHeader :title="t('vlan.labelPlural')" :subtitle="t('vlan.subtitle')">
      <template #actions>
        <Button v-if="isAdmin" variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('vlan.new') }}
        </Button>
      </template>
    </PageHeader>

    <DataTable
      :columns="columns"
      :rows="items"
      :loading="loading"
      :empty-title="t('vlan.labelPlural')"
      :empty-description="t('vlan.empty')"
    >
      <template v-if="isAdmin" #empty-action>
        <Button variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('vlan.new') }}
        </Button>
      </template>
      <template #cell-vlan_id="{ row }">
        <VlanBadge :vlan="row" compact />
      </template>
      <template #cell-description="{ row }">
        <span class="text-fg-muted">{{ row.description || '—' }}</span>
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

    <VlanEditor :open="editorOpen" :vlan="editing" @close="editorOpen = false" @saved="onSaved" />

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
