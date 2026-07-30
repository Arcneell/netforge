<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Plus, Pencil, Trash2, Search, X } from '@lucide/vue'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Input from '@/components/ui/Input.vue'
import Select from '@/components/ui/Select.vue'
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
const { notify } = useApiErrorMessage()
const router = useRouter()

const items = ref<Device[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)

const query = ref('')
const typeFilter = ref<DeviceType | ''>('')
const debouncedQuery = useDebounce(query, 300)

const deleteTarget = ref<Device | null>(null)
const deleting = ref(false)

// Sequence guard: a stale response from an earlier filter combination
// must NOT overwrite the fresh visible rows. Reproduces by toggling
// filters quickly on a slow backend.
let loadSeq = 0

async function load() {
  const seq = ++loadSeq
  loading.value = true
  try {
    const res = await devicesApi.list({
      page: page.value,
      page_size: pageSize,
      q: debouncedQuery.value || undefined,
      type: typeFilter.value || undefined,
    })
    if (seq !== loadSeq) return
    items.value = res.items
    total.value = res.total
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

onMounted(load)
watch([debouncedQuery, typeFilter], () => {
  page.value = 1
  load()
})

const hasActiveFilters = computed(() => query.value.trim().length > 0 || typeFilter.value !== '')

function clearFilters() {
  query.value = ''
  // Settle the debounce immediately so the watcher that follows reads the
  // empty query instead of the 300ms-stale one and re-issues the request
  // with the previous term still attached.
  debouncedQuery.flush()
  typeFilter.value = ''
}

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

// Create and edit are full pages, not modals — see components/FormPage.vue.
function onNew() {
  router.push({ name: 'device-new' })
}
function onEdit(d: Device) {
  router.push({ name: 'device-edit', params: { id: d.id } })
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
    notify(err)
  } finally {
    deleting.value = false
  }
}

// Wrap in computed so column labels follow the i18n locale (otherwise
// the header row stays in the language active when the view mounted).
const columns = computed<DataTableColumn[]>(() => [
  { key: 'name', label: t('device.fields.name') },
  { key: 'type', label: t('device.fields.type'), cellClass: 'w-28' },
  { key: 'vendor', label: t('device.fields.vendor'), hideOnSm: true },
  { key: 'model', label: t('device.fields.model'), hideOnSm: true },
  { key: 'serial', label: t('device.fields.serial'), hideOnSm: true, cellClass: 'font-mono' },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
])
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
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

    <!-- Same toolbar shape as the other list pages: search first, then the
         filters, then the result count pushed right. -->
    <div class="nf-toolbar">
      <div class="relative flex-1 min-w-[14rem] max-w-sm">
        <Search
          class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-fg-subtle pointer-events-none z-10"
          aria-hidden="true"
        />
        <Input
          v-model="query"
          type="search"
          :placeholder="t('common.search')"
          :aria-label="t('common.search')"
          class="pl-9 pr-9"
          autocomplete="off"
          spellcheck="false"
        />
        <button
          v-if="query"
          type="button"
          class="absolute right-1.5 top-1/2 -translate-y-1/2 inline-flex items-center justify-center w-6 h-6 rounded text-fg-muted hover:bg-surface-hover hover:text-fg transition-colors duration-150 ease-soft"
          :aria-label="t('common.reset')"
          @click="query = ''"
        >
          <X class="w-3.5 h-3.5" aria-hidden="true" />
        </button>
      </div>

      <div class="w-44">
        <Select
          :model-value="typeFilter"
          :options="typeOptions"
          :aria-label="t('device.fields.type')"
          @update:model-value="(v) => (typeFilter = v as DeviceType | '')"
        />
      </div>

      <Button v-if="hasActiveFilters" variant="ghost" size="sm" @click="clearFilters">
        <X class="w-3.5 h-3.5" aria-hidden="true" />
        {{ t('common.clearFilters') }}
      </Button>

      <span class="ml-auto text-sm text-fg-muted tabular-nums whitespace-nowrap" aria-live="polite">
        {{ t('common.resultCount', total) }}
      </span>
    </div>

    <DataTable
      :columns="columns"
      :rows="items"
      :loading="loading"
      :empty-title="hasActiveFilters ? t('common.noMatch.title') : t('common.empty.title')"
      :empty-description="
        hasActiveFilters ? t('common.noMatch.description') : t('device.emptyHint')
      "
    >
      <template #empty-action>
        <Button v-if="hasActiveFilters" variant="secondary" @click="clearFilters">
          <X class="w-4 h-4" aria-hidden="true" />
          {{ t('common.clearFilters') }}
        </Button>
        <Button v-else-if="isAdmin" variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('device.new') }}
        </Button>
      </template>
      <template #cell-name="{ row }">
        <span class="font-medium text-fg">{{ row.name }}</span>
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
