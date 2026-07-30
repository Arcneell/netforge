<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight, Diff, Search, TriangleAlert } from '@lucide/vue'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import Segmented, { type SegmentedOption } from '@/components/ui/Segmented.vue'
import Select from '@/components/ui/Select.vue'
import EmptyState from '@/components/EmptyState.vue'
import DataTable, { type DataTableColumn } from '@/components/DataTable.vue'
import { snapshotsApi } from '@/api/endpoints/snapshots'
import type { SnapshotChange, SnapshotCompareResponse } from '@/api/endpoints/snapshots'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'
import { formatDate, formatNumber } from '@/utils/formatters'

const { t } = useI18n()
const { describe } = useApiErrorMessage()
const { error: toastError } = useToast()

// Default range: the last 7 days. `datetime-local` wants "YYYY-MM-DDTHH:mm"
// in the operator's TZ; we convert to ISO 8601 before posting.
function defaultFrom(): string {
  const d = new Date()
  d.setDate(d.getDate() - 7)
  return formatLocal(d)
}
function defaultTo(): string {
  return formatLocal(new Date())
}
function formatLocal(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const fromTs = ref(defaultFrom())
const toTs = ref(defaultTo())
const entityFilter = ref('')

const loading = ref(false)
const result = ref<SnapshotCompareResponse | null>(null)

const ENTITIES = ['site', 'room', 'vlan', 'subnet', 'ip', 'device', 'switch', 'port', 'link']

// The empty value means "every entity" — `run()` drops it from the request.
// Computed so the "all" label follows a locale switch; the entity names
// themselves are the API's own identifiers and stay untranslated.
const entityOptions = computed<{ value: string; label: string }[]>(() => [
  { value: '', label: t('common.all') },
  ...ENTITIES.map((e) => ({ value: e, label: e })),
])

// --- Quick ranges ---------------------------------------------------------- #
// Presets only rewrite the two datetime fields — the request itself is
// unchanged. `applyingPreset` keeps the watcher below from immediately
// demoting the selection to "custom" when we set the fields ourselves.
type Preset = '24h' | '7d' | '30d' | 'custom'
const preset = ref<Preset>('7d')
let applyingPreset = false

const presetOptions = computed<SegmentedOption<Preset>[]>(() => [
  { value: '24h', label: t('snapshots.compare.preset24h') },
  { value: '7d', label: t('snapshots.compare.preset7d') },
  { value: '30d', label: t('snapshots.compare.preset30d') },
])

const PRESET_DAYS: Record<Exclude<Preset, 'custom'>, number> = { '24h': 1, '7d': 7, '30d': 30 }

function applyPreset(p: Preset) {
  if (p === 'custom') return
  const now = new Date()
  const from = new Date(now)
  from.setDate(from.getDate() - PRESET_DAYS[p])
  applyingPreset = true
  fromTs.value = formatLocal(from)
  toTs.value = formatLocal(now)
  preset.value = p
  nextTick(() => {
    applyingPreset = false
  })
}

watch([fromTs, toTs], () => {
  if (!applyingPreset) preset.value = 'custom'
})

// Advisory only — the request still goes through if the operator insists,
// exactly as it did before. This just names the mistake on screen.
const rangeInvalid = computed(() => {
  const a = new Date(fromTs.value).getTime()
  const b = new Date(toTs.value).getTime()
  return Number.isFinite(a) && Number.isFinite(b) && b < a
})

const summaryEntities = computed(() =>
  result.value ? Object.entries(result.value.summary.by_entity) : [],
)

const summaryTotals = computed(() =>
  summaryEntities.value.reduce(
    (acc, [, b]) => ({
      created: acc.created + b.created,
      updated: acc.updated + b.updated,
      deleted: acc.deleted + b.deleted,
      transient: acc.transient + b.transient,
    }),
    { created: 0, updated: 0, deleted: 0, transient: 0 },
  ),
)

// DataTable keys rows by `id`; the API pairs entity + entity_id instead.
const changeRows = computed<(SnapshotChange & { id: string })[]>(() =>
  (result.value?.changes ?? []).map((c) => ({ ...c, id: `${c.entity}:${c.entity_id}` })),
)

const changeColumns = computed<DataTableColumn<SnapshotChange & { id: string }>[]>(() => [
  { key: 'entity', label: t('snapshots.compare.colEntity'), cellClass: 'w-32' },
  { key: 'entity_id', label: 'ID', align: 'right', cellClass: 'w-20' },
  { key: 'status', label: t('snapshots.compare.colStatus'), cellClass: 'w-28' },
  { key: 'last_action_at', label: t('snapshots.compare.colWhen'), cellClass: 'w-48' },
  {
    key: 'actions_count',
    label: t('snapshots.compare.colActions'),
    align: 'right',
    cellClass: 'w-24',
  },
  { key: 'fields_changed', label: t('snapshots.compare.colFields') },
])

async function run() {
  if (loading.value) return
  loading.value = true
  try {
    const from = new Date(fromTs.value).toISOString()
    const to = new Date(toTs.value).toISOString()
    result.value = await snapshotsApi.compare({
      from,
      to,
      entity: entityFilter.value || undefined,
    })
  } catch (err) {
    toastError(describe(err))
  } finally {
    loading.value = false
  }
}

function statusTone(status: string): 'success' | 'primary' | 'warning' | 'danger' {
  switch (status) {
    case 'created':
      return 'success'
    case 'updated':
      return 'primary'
    case 'deleted':
      return 'danger'
    case 'transient':
      return 'warning'
    default:
      return 'primary'
  }
}
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="t('snapshots.compare.title')" :subtitle="t('snapshots.compare.subtitle')">
      <template #help>
        <HelpTooltip :text="t('snapshots.compare.help')" placement="bottom" />
      </template>
    </PageHeader>

    <!-- One comparison control: the two ends of the window sit either side of
         an arrow, the entity filter narrows it, and the run button closes the
         sentence. Help triggers live next to the labels but OUTSIDE the
         `<label>` wrappers — otherwise clicking `?` activates the label and
         focuses (and on Safari, blurs) the bound input. Codex P2 on #71. -->
    <section class="nf-card p-4 sm:p-5 mb-6">
      <div class="flex flex-wrap items-end gap-x-4 gap-y-3">
        <div class="flex-1 min-w-[260px] grid grid-cols-1 sm:grid-cols-[1fr_auto_1fr] gap-2">
          <div>
            <div class="nf-label mb-1 flex items-center gap-1">
              <label for="snapshot-from">{{ t('snapshots.compare.from') }}</label>
              <HelpTooltip :text="t('snapshots.compare.helpFrom')" />
            </div>
            <Input id="snapshot-from" v-model="fromTs" type="datetime-local" autocomplete="off" />
          </div>
          <div class="hidden sm:flex items-center justify-center pb-2 text-fg-subtle">
            <ArrowRight class="w-4 h-4" aria-hidden="true" />
          </div>
          <div>
            <div class="nf-label mb-1 flex items-center gap-1">
              <label for="snapshot-to">{{ t('snapshots.compare.to') }}</label>
              <HelpTooltip :text="t('snapshots.compare.helpTo')" />
            </div>
            <Input id="snapshot-to" v-model="toTs" type="datetime-local" autocomplete="off" />
          </div>
        </div>

        <div class="w-full sm:w-52">
          <div class="nf-label mb-1 flex items-center gap-1">
            <label for="snapshot-entity">{{ t('snapshots.compare.entity') }}</label>
            <HelpTooltip :text="t('snapshots.compare.helpEntity')" />
          </div>
          <Select id="snapshot-entity" v-model="entityFilter" :options="entityOptions" />
        </div>

        <div class="flex items-center gap-2">
          <Button variant="primary" :loading="loading" @click="run">
            <Search class="w-4 h-4" aria-hidden="true" />
            {{ t('snapshots.compare.run') }}
          </Button>
          <HelpTooltip :text="t('snapshots.compare.helpRun')" />
        </div>
      </div>

      <div class="mt-4 pt-4 border-t border-border flex flex-wrap items-center gap-x-3 gap-y-2">
        <span class="nf-label">{{ t('snapshots.compare.presetsLabel') }}</span>
        <Segmented
          :model-value="preset"
          :options="presetOptions"
          :aria-label="t('snapshots.compare.presetsLabel')"
          @update:model-value="applyPreset"
        />
        <p v-if="rangeInvalid" class="inline-flex items-center gap-1.5 text-xs text-warning">
          <TriangleAlert class="w-3.5 h-3.5" aria-hidden="true" />
          {{ t('snapshots.compare.rangeInvalid') }}
        </p>
      </div>
    </section>

    <!-- Summary -->
    <section v-if="result" class="nf-card p-4 sm:p-5 mb-6">
      <div class="flex items-baseline justify-between flex-wrap gap-2 mb-3">
        <h2 class="nf-section-title">{{ t('snapshots.compare.summary') }}</h2>
        <p class="text-xs text-fg-muted tabular-nums">
          {{
            t('snapshots.compare.summaryMeta', {
              total: result.summary.total_audit_rows,
              orphan: result.summary.orphan_rows,
            })
          }}
        </p>
      </div>

      <div v-if="summaryEntities.length" class="overflow-x-auto">
        <table class="w-full text-base">
          <thead>
            <tr class="border-b border-border">
              <th class="nf-label text-left py-2 pr-3">
                {{ t('snapshots.compare.colEntity') }}
              </th>
              <th class="nf-label text-right py-2 px-3">
                {{ t('snapshots.compare.colCreated') }}
              </th>
              <th class="nf-label text-right py-2 px-3">
                {{ t('snapshots.compare.colUpdated') }}
              </th>
              <th class="nf-label text-right py-2 px-3">
                {{ t('snapshots.compare.colDeleted') }}
              </th>
              <th class="nf-label text-right py-2 pl-3">
                {{ t('snapshots.compare.colTransient') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="[ent, b] in summaryEntities"
              :key="ent"
              class="border-b border-border last:border-0 transition-colors duration-150 ease-soft hover:bg-surface-hover"
            >
              <td class="py-2 pr-3 font-mono text-sm text-fg">{{ ent }}</td>
              <td class="py-2 px-3 text-right tabular-nums font-mono">
                <span :class="b.created ? 'text-success' : 'text-fg-subtle'">{{ b.created }}</span>
              </td>
              <td class="py-2 px-3 text-right tabular-nums font-mono">
                <span
                  :class="b.updated ? 'text-primary-600 dark:text-primary-400' : 'text-fg-subtle'"
                >
                  {{ b.updated }}
                </span>
              </td>
              <td class="py-2 px-3 text-right tabular-nums font-mono">
                <span :class="b.deleted ? 'text-danger' : 'text-fg-subtle'">{{ b.deleted }}</span>
              </td>
              <td class="py-2 pl-3 text-right tabular-nums font-mono">
                <span :class="b.transient ? 'text-warning' : 'text-fg-subtle'">
                  {{ b.transient }}
                </span>
              </td>
            </tr>
          </tbody>
          <tfoot v-if="summaryEntities.length > 1">
            <tr class="border-t border-border-strong">
              <td class="py-2 pr-3 nf-label">{{ t('snapshots.compare.colTotal') }}</td>
              <td class="py-2 px-3 text-right tabular-nums font-mono text-fg">
                {{ summaryTotals.created }}
              </td>
              <td class="py-2 px-3 text-right tabular-nums font-mono text-fg">
                {{ summaryTotals.updated }}
              </td>
              <td class="py-2 px-3 text-right tabular-nums font-mono text-fg">
                {{ summaryTotals.deleted }}
              </td>
              <td class="py-2 pl-3 text-right tabular-nums font-mono text-fg">
                {{ summaryTotals.transient }}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p v-else class="text-base text-fg-muted">{{ t('snapshots.compare.noChanges') }}</p>
    </section>

    <!-- Per-entity change list -->
    <section v-if="result && changeRows.length">
      <div class="flex items-baseline justify-between flex-wrap gap-2 mb-3">
        <h2 class="nf-section-title">{{ t('snapshots.compare.changesTitle') }}</h2>
        <p class="text-xs text-fg-muted tabular-nums">
          {{ t('snapshots.compare.changesCount', { count: formatNumber(changeRows.length) }) }}
        </p>
      </div>
      <DataTable :columns="changeColumns" :rows="changeRows">
        <template #cell-entity="{ row }">
          <span class="font-mono text-sm text-fg">{{ row.entity }}</span>
        </template>
        <template #cell-entity_id="{ row }">
          <span class="font-mono text-fg-muted">#{{ row.entity_id }}</span>
        </template>
        <template #cell-status="{ row }">
          <Badge :tone="statusTone(row.status)">{{ row.status }}</Badge>
        </template>
        <template #cell-last_action_at="{ row }">
          <span class="text-fg-muted whitespace-nowrap font-mono text-sm">
            {{ formatDate(row.last_action_at) }}
          </span>
        </template>
        <template #cell-actions_count="{ row }">
          <span class="tabular-nums font-mono">{{ row.actions_count }}</span>
        </template>
        <template #cell-fields_changed="{ row }">
          <span class="text-sm text-fg-muted font-mono break-words">
            {{ row.fields_changed.join(', ') || '—' }}
          </span>
        </template>
      </DataTable>
    </section>

    <!-- Ran, but the window is quiet: say how to widen it and offer the click. -->
    <section v-else-if="result" class="nf-card">
      <EmptyState
        :icon="Diff"
        :title="t('snapshots.compare.noChangesTitle')"
        :description="t('snapshots.compare.noChangesDescription')"
        size="sm"
      >
        <template #action>
          <Button variant="secondary" size="sm" @click="applyPreset('30d')">
            {{ t('snapshots.compare.widenRange') }}
          </Button>
        </template>
      </EmptyState>
    </section>

    <!-- Nothing run yet. -->
    <section v-else class="nf-card">
      <EmptyState
        :icon="Diff"
        :title="t('snapshots.compare.pickTitle')"
        :description="t('snapshots.compare.pickDescription')"
        size="sm"
      >
        <template #action>
          <Button variant="primary" size="sm" :loading="loading" @click="run">
            <Search class="w-4 h-4" aria-hidden="true" />
            {{ t('snapshots.compare.run') }}
          </Button>
        </template>
      </EmptyState>
    </section>
  </div>
</template>
