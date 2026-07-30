<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Download, Eye, PlusCircle, PencilLine, Trash2, ListFilter } from '@lucide/vue'
import PageHeader from '@/components/PageHeader.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import Pagination from '@/components/Pagination.vue'
import Button from '@/components/ui/Button.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Modal from '@/components/ui/Modal.vue'
import Select from '@/components/ui/Select.vue'
import Segmented, { type SegmentedOption } from '@/components/ui/Segmented.vue'
import AuditDiff from '@/components/AuditDiff.vue'
import { auditApi } from '@/api'
import type { AuditAction, AuditLog } from '@/api'
import { formatDate, formatNumber, formatRelativeTime } from '@/utils/formatters'

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

// The action filter is a four-way switch, not a dropdown: there are only
// three actions and the operator flips between them constantly.
const actionSegments = computed<SegmentedOption<AuditAction | ''>[]>(() => [
  { value: '', label: t('common.all') },
  { value: 'create', label: t('audit.actions.create'), icon: PlusCircle },
  { value: 'update', label: t('audit.actions.update'), icon: PencilLine },
  { value: 'delete', label: t('audit.actions.delete'), icon: Trash2 },
])

const hasFilters = computed(() => !!entityFilter.value || !!actionFilter.value)

function resetFilters() {
  entityFilter.value = ''
  actionFilter.value = ''
}

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
  { key: 'action', label: t('audit.fields.action'), cellClass: 'w-28' },
  { key: 'entity', label: t('audit.fields.entity'), cellClass: 'w-32' },
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
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
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

    <!-- Every filter in one bar, with the result count and the escape hatch
         parked on the right so the row reads left-to-right: narrow, then how
         much is left, then undo. -->
    <div class="nf-toolbar" role="group" :aria-label="t('audit.filtersAria')">
      <Segmented
        :model-value="actionFilter"
        :options="actionSegments"
        :aria-label="t('audit.fields.action')"
        @update:model-value="(v) => (actionFilter = v)"
      />
      <div class="w-full sm:w-52">
        <Select
          :model-value="entityFilter"
          :options="entityOptions"
          :aria-label="t('audit.filters.entity')"
          @update:model-value="(v) => (entityFilter = String(v))"
        />
      </div>
      <div class="ml-auto flex items-center gap-2">
        <span class="text-xs text-fg-muted tabular-nums" aria-live="polite">
          {{ t('audit.resultCount', { count: formatNumber(total) }) }}
        </span>
        <Button v-if="hasFilters" variant="ghost" size="sm" @click="resetFilters">
          {{ t('common.reset') }}
        </Button>
      </div>
    </div>

    <DataTable
      :columns="columns"
      :rows="items"
      :loading="loading"
      :empty-title="t('audit.emptyTitle')"
      :empty-description="t('audit.emptyDescription')"
      clickable
      @row-click="(r) => (selected = r)"
    >
      <template v-if="hasFilters" #empty-action>
        <Button variant="secondary" size="sm" @click="resetFilters">
          <ListFilter class="w-4 h-4" aria-hidden="true" />
          {{ t('common.reset') }}
        </Button>
      </template>
      <template #cell-created_at="{ row }">
        <div class="flex flex-col leading-tight">
          <span class="text-fg">{{ formatRelativeTime(row.created_at) }}</span>
          <span class="text-2xs text-fg-subtle font-mono">{{ formatDate(row.created_at) }}</span>
        </div>
      </template>
      <template #cell-action="{ row }">
        <Badge :tone="actionTone[row.action]">{{ t(`audit.actions.${row.action}`) }}</Badge>
      </template>
      <template #cell-entity="{ row }">
        <span class="font-mono text-sm text-fg">{{ row.entity }}</span>
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
      <div v-if="selected" class="space-y-5">
        <section>
          <p class="nf-label mb-2">{{ t('audit.metaTitle') }}</p>
          <dl
            class="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-3 p-3 rounded-lg bg-muted/60 border border-border"
          >
            <div class="min-w-0">
              <dt class="text-xs text-fg-muted">{{ t('audit.fields.when') }}</dt>
              <dd class="text-sm text-fg font-mono mt-0.5">
                {{ formatDate(selected.created_at) }}
              </dd>
            </div>
            <div class="min-w-0">
              <dt class="text-xs text-fg-muted">{{ t('audit.fields.user') }}</dt>
              <dd class="text-sm text-fg font-mono mt-0.5">#{{ selected.user_id ?? '—' }}</dd>
            </div>
            <div class="min-w-0">
              <dt class="text-xs text-fg-muted">{{ t('audit.fields.ip') }}</dt>
              <dd class="text-sm text-fg font-mono break-all mt-0.5">
                {{ selected.ip_address || '—' }}
              </dd>
            </div>
            <div class="min-w-0">
              <dt class="text-xs text-fg-muted">{{ t('audit.fields.userAgent') }}</dt>
              <dd class="text-2xs text-fg-muted break-all mt-0.5">
                {{ selected.user_agent || '—' }}
              </dd>
            </div>
          </dl>
        </section>
        <section>
          <p class="nf-label mb-2">{{ t('audit.fields.changes') }}</p>
          <AuditDiff :changes="selected.changes" :action="selected.action" />
        </section>
      </div>
    </Modal>
  </div>
</template>
