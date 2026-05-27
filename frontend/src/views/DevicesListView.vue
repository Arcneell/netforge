<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Pencil, Trash2, Search } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
import DeviceEditor from '@/components/editors/DeviceEditor.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { devicesApi } from '@/api'
import type { Device, DeviceType } from '@/api'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useDebounce } from '@/composables/useDebounce'

const { t } = useI18n()
const { isAdmin } = useAuth()
const { success } = useToast()
const { describe } = useApiErrorMessage()

const items = ref<Device[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)

const query = ref('')
const typeFilter = ref<DeviceType | ''>('')
const debouncedQuery = useDebounce(query, 300)

const editorOpen = ref(false)
const editing = ref<Device | null>(null)
const deleteTarget = ref<Device | null>(null)
const deleting = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await devicesApi.list({
      page: page.value,
      page_size: pageSize,
      q: debouncedQuery.value || undefined,
      type: typeFilter.value || undefined,
    })
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch([debouncedQuery, typeFilter], () => {
  page.value = 1
  load()
})

const typeOptions = computed(() => [
  { value: '', label: t('common.all') },
  ...(
    [
      'server',
      'desktop',
      'laptop',
      'printer',
      'phone',
      'ap',
      'camera',
      'ups',
      'other',
    ] as DeviceType[]
  ).map((tp) => ({ value: tp, label: t(`device.types.${tp}`) })),
])

function onNew() {
  editing.value = null
  editorOpen.value = true
}
function onEdit(d: Device) {
  editing.value = d
  editorOpen.value = true
}
async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await devicesApi.delete(deleteTarget.value.id)
    success(t('common.success'))
    deleteTarget.value = null
    load()
  } catch (err) {
    void describe(err)
  } finally {
    deleting.value = false
  }
}

// Wrap in computed so column labels follow the i18n locale (otherwise
// the header row stays in the language active when the view mounted).
const columns = computed<DataTableColumn[]>(() => [
  { key: 'name', label: t('device.fields.name'), cellClass: 'font-medium' },
  { key: 'type', label: t('device.fields.type'), cellClass: 'w-28' },
  { key: 'vendor', label: t('device.fields.vendor'), hideOnSm: true },
  { key: 'model', label: t('device.fields.model'), hideOnSm: true },
  { key: 'serial', label: t('device.fields.serial'), hideOnSm: true, cellClass: 'font-mono' },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
])
</script>

<template>
  <div class="p-4 sm:p-6 max-w-7xl mx-auto">
    <PageHeader :title="t('device.labelPlural')" :subtitle="t('device.subtitle')">
      <template #help>
        <HelpTooltip :text="t('device.pageHelp')" placement="bottom" />
      </template>
      <template #actions>
        <Button v-if="isAdmin" variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('device.new') }}
        </Button>
      </template>
    </PageHeader>

    <div class="flex flex-wrap items-center gap-2 mb-4">
      <div class="relative flex-1 min-w-[12rem] max-w-sm">
        <Search
          class="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-fg-muted pointer-events-none"
          aria-hidden="true"
        />
        <Input
          v-model="query"
          :placeholder="t('common.search')"
          class="pl-8"
          :aria-label="t('common.search')"
          autocomplete="off"
        />
      </div>
      <div class="w-44">
        <Select
          :model-value="typeFilter"
          :options="typeOptions"
          :aria-label="t('device.fields.type')"
          @update:model-value="(v) => (typeFilter = v as DeviceType | '')"
        />
      </div>
    </div>

    <DataTable
      :columns="columns"
      :rows="items"
      :loading="loading"
      :empty-title="t('device.labelPlural')"
      :empty-description="t('device.empty')"
    >
      <template v-if="isAdmin" #empty-action>
        <Button variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('device.new') }}
        </Button>
      </template>
      <template #cell-type="{ row }">
        <Badge tone="neutral">{{ t(`device.types.${row.type}`) }}</Badge>
      </template>
      <template #cell-vendor="{ row }">
        <span class="text-fg-muted">{{ row.vendor || '—' }}</span>
      </template>
      <template #cell-model="{ row }">
        <span class="text-fg-muted">{{ row.model || '—' }}</span>
      </template>
      <template #cell-serial="{ row }">
        <span class="text-fg-muted">{{ row.serial || '—' }}</span>
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

    <DeviceEditor :open="editorOpen" :device="editing" @close="editorOpen = false" @saved="load" />
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
