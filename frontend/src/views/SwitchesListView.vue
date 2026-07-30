<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Plus, Pencil, Trash2 } from '@lucide/vue'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { switchesApi } from '@/api'
import type { Switch } from '@/api'
import { useAuth } from '@/composables/useAuth'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'

const { t } = useI18n()
const { isAdmin } = useAuth()
const { success } = useToast()
const { notify } = useApiErrorMessage()
const router = useRouter()

const items = ref<Switch[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)

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

// Create and edit are full pages, not modals — see components/FormPage.vue.
function onNew() {
  router.push({ name: 'switch-new' })
}
function onEdit(s: Switch) {
  router.push({ name: 'switch-edit', params: { id: s.id } })
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
    notify(err)
  } finally {
    deleting.value = false
  }
}

// Wrap in computed so column labels follow the i18n locale.
const columns = computed<DataTableColumn[]>(() => [
  { key: 'name', label: t('switch.fields.name') },
  { key: 'vendor', label: t('switch.fields.vendor'), hideOnSm: true },
  { key: 'model', label: t('switch.fields.model'), hideOnSm: true },
  { key: 'management_ip', label: t('switch.fields.managementIp'), cellClass: 'font-mono' },
  { key: 'port_count', label: t('switch.fields.portCount'), align: 'right', cellClass: 'w-24' },
  { key: 'actions', label: t('common.actions'), align: 'right', cellClass: 'w-32' },
])
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="t('switch.labelPlural')" :subtitle="t('switch.subtitle')">
      <template #help>
        <HelpTooltip :text="t('switch.pageHelp')" placement="bottom" />
      </template>
      <template #actions>
        <Button v-if="isAdmin" variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('switch.new') }}
        </Button>
      </template>
    </PageHeader>

    <!-- Same toolbar slot as the other list pages. `/switches` exposes no
         search param, so the bar carries only the honest result count —
         filtering the current page client-side would lie about the total. -->
    <div class="nf-toolbar">
      <span class="ml-auto text-sm text-fg-muted tabular-nums whitespace-nowrap" aria-live="polite">
        {{ t('common.resultCount', total) }}
      </span>
    </div>

    <DataTable
      :columns="columns"
      :rows="items"
      :loading="loading"
      :empty-title="t('common.empty.title')"
      :empty-description="t('switch.empty')"
      clickable
      @row-click="onRowClick"
    >
      <template v-if="isAdmin" #empty-action>
        <Button variant="primary" @click="onNew">
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('switch.new') }}
        </Button>
      </template>
      <!-- The name is the thing you click: it carries the row's identity and
           picks up the accent on row hover so the target is unambiguous. -->
      <template #cell-name="{ row }">
        <span
          class="font-medium text-fg group-hover/row:text-primary-600 dark:group-hover/row:text-primary-400 transition-colors duration-150 ease-soft"
        >
          {{ row.name }}
        </span>
      </template>
      <template #cell-vendor="{ row }">
        <span class="text-fg-muted">{{ row.vendor || '—' }}</span>
      </template>
      <template #cell-model="{ row }">
        <span class="text-fg-muted">{{ row.model || '—' }}</span>
      </template>
      <template #cell-management_ip="{ row }">
        <span v-if="row.management_ip" class="text-fg-muted">{{ row.management_ip }}</span>
        <span v-else class="text-fg-subtle">—</span>
      </template>
      <template #cell-port_count="{ row }">
        <span class="tabular-nums text-fg-muted">{{ row.port_count }}</span>
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
