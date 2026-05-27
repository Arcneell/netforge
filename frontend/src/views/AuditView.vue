<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Download, Eye } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Modal from '@/components/ui/Modal.vue'
import Select from '@/components/ui/Select.vue'
import AuditDiff from '@/components/AuditDiff.vue'
import { auditApi } from '@/api'
import type { AuditAction, AuditLog } from '@/api'
import { formatDate, formatRelativeTime } from '@/utils/formatters'

const { t } = useI18n()

const items = ref<AuditLog[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)

const entityFilter = ref('')
const actionFilter = ref<AuditAction | ''>('')
const selected = ref<AuditLog | null>(null)

const entityOptions = computed(() => [
  { value: '', label: t('common.all') },
  { value: 'site', label: t('site.label') },
  { value: 'room', label: t('room.label') },
  { value: 'vlan', label: t('vlan.label') },
  { value: 'subnet', label: t('subnet.label') },
  { value: 'ip', label: t('ip.label') },
  { value: 'device', label: t('device.label') },
  { value: 'switch', label: t('switch.label') },
  { value: 'port', label: t('port.label') },
])

const actionOptions = computed(() => [
  { value: '', label: t('common.all') },
  { value: 'create', label: t('audit.actions.create') },
  { value: 'update', label: t('audit.actions.update') },
  { value: 'delete', label: t('audit.actions.delete') },
])

// Sequence guard: a stale response from an earlier filter combination
// must NOT overwrite the fresh visible rows when the user toggles
// entity / action filters quickly. Same pattern as DevicesListView.
let loadSeq = 0

async function load() {
  const seq = ++loadSeq
  loading.value = true
  try {
    const res = await auditApi.list({
      page: page.value,
      page_size: pageSize,
      entity: entityFilter.value || undefined,
      action: actionFilter.value || undefined,
    })
    if (seq !== loadSeq) return
    items.value = res.items
    total.value = res.total
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

onMounted(load)
watch([entityFilter, actionFilter], () => {
  page.value = 1
  load()
})

const actionTone: Record<AuditAction, 'success' | 'primary' | 'danger'> = {
  create: 'success',
  update: 'primary',
  delete: 'danger',
}

// Wrap in computed so column labels follow the active i18n locale —
// without this, switching language leaves the header row in the
// originally-mounted language until the user re-enters the page.
const columns = computed<DataTableColumn[]>(() => [
  { key: 'created_at', label: t('audit.fields.when'), cellClass: 'w-44 whitespace-nowrap' },
  { key: 'action', label: t('audit.fields.action'), cellClass: 'w-24' },
  { key: 'entity', label: t('audit.fields.entity'), cellClass: 'w-28' },
  {
    key: 'entity_id',
    label: t('audit.fields.entityId'),
    align: 'right',
    cellClass: 'w-20 font-mono',
  },
  { key: 'user_id', label: t('audit.fields.user'), align: 'right', cellClass: 'w-20 font-mono' },
  { key: 'actions', label: '', align: 'right', cellClass: 'w-16' },
])

function exportCsv() {
  // Carry the visible filters into the export so what the admin sees on
  // screen matches what lands in the file. The export endpoint accepts the
  // same filter params as the list endpoint.
  const params = new URLSearchParams()
  if (entityFilter.value) params.set('entity', entityFilter.value)
  if (actionFilter.value) params.set('action', actionFilter.value)
  const qs = params.toString()
  const url = qs ? `/api/exports/audit?${qs}` : '/api/exports/audit'
  window.open(url, '_blank', 'noopener')
}
</script>

<template>
  <div class="p-4 sm:p-6 max-w-7xl mx-auto">
    <PageHeader :title="t('nav.audit')" :subtitle="t('audit.subtitle')">
      <template #help>
        <HelpTooltip :text="t('audit.help')" placement="bottom" />
      </template>
      <template #actions>
        <Button variant="secondary" @click="exportCsv">
          <Download class="w-4 h-4" aria-hidden="true" />
          {{ t('audit.exportCsv') }}
        </Button>
      </template>
    </PageHeader>

    <div class="flex flex-wrap items-center gap-2 mb-4">
      <div class="w-48">
        <Select
          :model-value="entityFilter"
          :options="entityOptions"
          :aria-label="t('audit.filters.entity')"
          @update:model-value="(v) => (entityFilter = String(v))"
        />
      </div>
      <div class="w-44">
        <Select
          :model-value="actionFilter"
          :options="actionOptions"
          :aria-label="t('audit.fields.action')"
          @update:model-value="(v) => (actionFilter = v as AuditAction | '')"
        />
      </div>
    </div>

    <DataTable
      :columns="columns"
      :rows="items"
      :loading="loading"
      :empty-title="t('nav.audit')"
      :empty-description="t('dashboard.recent.empty')"
      clickable
      @row-click="(r) => (selected = r)"
    >
      <template #cell-created_at="{ row }">
        <div class="flex flex-col">
          <span class="text-fg">{{ formatRelativeTime(row.created_at) }}</span>
          <span class="text-[10px] text-fg-muted font-mono">{{ formatDate(row.created_at) }}</span>
        </div>
      </template>
      <template #cell-action="{ row }">
        <Badge :tone="actionTone[row.action]">{{ t(`audit.actions.${row.action}`) }}</Badge>
      </template>
      <template #cell-entity_id="{ row }">
        <span class="text-fg-muted">{{ row.entity_id ?? '—' }}</span>
      </template>
      <template #cell-user_id="{ row }">
        <span class="text-fg-muted">{{ row.user_id ?? '—' }}</span>
      </template>
      <template #cell-actions="{ row }">
        <Button
          variant="ghost"
          size="sm"
          :aria-label="t('audit.viewDiff')"
          @click.stop="selected = row"
        >
          <Eye class="w-4 h-4" aria-hidden="true" />
        </Button>
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

    <Modal
      :open="!!selected"
      :title="
        selected
          ? `${selected.entity} #${selected.entity_id ?? '—'} · ${t(`audit.actions.${selected.action}`)}`
          : ''
      "
      size="xl"
      @close="selected = null"
    >
      <div v-if="selected" class="space-y-4">
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <div>
            <p class="text-fg-muted">{{ t('audit.fields.when') }}</p>
            <p class="text-fg font-mono">{{ formatDate(selected.created_at) }}</p>
          </div>
          <div>
            <p class="text-fg-muted">{{ t('audit.fields.user') }}</p>
            <p class="text-fg font-mono">#{{ selected.user_id ?? '—' }}</p>
          </div>
          <div>
            <p class="text-fg-muted">{{ t('audit.fields.ip') }}</p>
            <p class="text-fg font-mono break-all">{{ selected.ip_address || '—' }}</p>
          </div>
          <div>
            <p class="text-fg-muted">{{ t('audit.fields.userAgent') }}</p>
            <p class="text-fg text-[11px] break-all">{{ selected.user_agent || '—' }}</p>
          </div>
        </div>
        <div>
          <p class="text-xs font-medium text-fg-muted uppercase tracking-wide mb-2">
            {{ t('audit.fields.changes') }}
          </p>
          <AuditDiff :changes="selected.changes" :action="selected.action" />
        </div>
      </div>
    </Modal>
  </div>
</template>
