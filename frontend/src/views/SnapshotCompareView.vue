<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Diff, Search } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import EmptyState from '@/components/EmptyState.vue'
import { snapshotsApi } from '@/api/endpoints/snapshots'
import type { SnapshotCompareResponse } from '@/api/endpoints/snapshots'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'
import { formatDate } from '@/utils/formatters'

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

const entityOptions = ['site', 'room', 'vlan', 'subnet', 'ip', 'device', 'switch', 'port', 'link']

const summaryEntities = computed(() =>
  result.value ? Object.entries(result.value.summary.by_entity) : [],
)

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
  <div class="p-4 sm:p-6 max-w-7xl mx-auto">
    <PageHeader :title="t('snapshots.compare.title')" :subtitle="t('snapshots.compare.subtitle')">
      <template #help>
        <HelpTooltip :text="t('snapshots.compare.help')" placement="bottom" />
      </template>
    </PageHeader>

    <!-- Range pickers. Help triggers live next to the labels but OUTSIDE the
         `<label>` wrappers — otherwise clicking `?` activates the label and
         focuses (and on Safari, blurs) the bound input. Codex P2 on #71. -->
    <div class="nf-card p-4 mb-4 grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
      <div class="text-sm">
        <div
          class="text-xs uppercase tracking-wider text-fg-muted font-semibold mb-1 flex items-center gap-1"
        >
          <label for="snapshot-from">{{ t('snapshots.compare.from') }}</label>
          <HelpTooltip :text="t('snapshots.compare.helpFrom')" />
        </div>
        <Input id="snapshot-from" v-model="fromTs" type="datetime-local" autocomplete="off" />
      </div>
      <div class="text-sm">
        <label
          for="snapshot-to"
          class="block text-xs uppercase tracking-wider text-fg-muted font-semibold mb-1"
        >
          {{ t('snapshots.compare.to') }}
        </label>
        <Input id="snapshot-to" v-model="toTs" type="datetime-local" autocomplete="off" />
      </div>
      <div class="text-sm">
        <div
          class="text-xs uppercase tracking-wider text-fg-muted font-semibold mb-1 flex items-center gap-1"
        >
          <label for="snapshot-entity">{{ t('snapshots.compare.entity') }}</label>
          <HelpTooltip :text="t('snapshots.compare.helpEntity')" />
        </div>
        <select
          id="snapshot-entity"
          v-model="entityFilter"
          class="w-full h-9 px-2 rounded border border-border bg-surface text-sm"
        >
          <option value="">{{ t('common.all') }}</option>
          <option v-for="e in entityOptions" :key="e" :value="e">{{ e }}</option>
        </select>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="primary" :loading="loading" @click="run">
          <Search class="w-4 h-4" aria-hidden="true" />
          {{ t('snapshots.compare.run') }}
        </Button>
        <HelpTooltip :text="t('snapshots.compare.helpRun')" />
      </div>
    </div>

    <!-- Summary -->
    <div v-if="result" class="nf-card p-4 mb-4">
      <div class="flex items-baseline justify-between flex-wrap gap-2 mb-3">
        <h2 class="text-sm font-semibold">{{ t('snapshots.compare.summary') }}</h2>
        <p class="text-xs text-fg-muted tabular-nums">
          {{
            t('snapshots.compare.summaryMeta', {
              total: result.summary.total_audit_rows,
              orphan: result.summary.orphan_rows,
            })
          }}
        </p>
      </div>
      <table v-if="summaryEntities.length" class="w-full text-sm">
        <thead>
          <tr class="text-[11px] uppercase tracking-wider text-fg-muted">
            <th class="text-left font-semibold py-1.5">{{ t('snapshots.compare.colEntity') }}</th>
            <th class="text-right font-semibold py-1.5">{{ t('snapshots.compare.colCreated') }}</th>
            <th class="text-right font-semibold py-1.5">{{ t('snapshots.compare.colUpdated') }}</th>
            <th class="text-right font-semibold py-1.5">{{ t('snapshots.compare.colDeleted') }}</th>
            <th class="text-right font-semibold py-1.5">
              {{ t('snapshots.compare.colTransient') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="[ent, b] in summaryEntities" :key="ent" class="border-t border-border/50">
            <td class="py-2 font-mono">{{ ent }}</td>
            <td class="py-2 text-right tabular-nums text-success">{{ b.created }}</td>
            <td class="py-2 text-right tabular-nums text-primary-500">{{ b.updated }}</td>
            <td class="py-2 text-right tabular-nums text-danger">{{ b.deleted }}</td>
            <td class="py-2 text-right tabular-nums text-warning">{{ b.transient }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="text-sm text-fg-muted">{{ t('snapshots.compare.noChanges') }}</p>
    </div>

    <!-- Per-entity change list -->
    <div v-if="result && result.changes.length" class="nf-card overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-surface">
          <tr class="text-[11px] uppercase tracking-wider text-fg-muted">
            <th class="text-left font-semibold px-3 py-2">
              {{ t('snapshots.compare.colEntity') }}
            </th>
            <th class="text-left font-semibold px-3 py-2">ID</th>
            <th class="text-left font-semibold px-3 py-2">
              {{ t('snapshots.compare.colStatus') }}
            </th>
            <th class="text-left font-semibold px-3 py-2">{{ t('snapshots.compare.colWhen') }}</th>
            <th class="text-left font-semibold px-3 py-2">
              {{ t('snapshots.compare.colActions') }}
            </th>
            <th class="text-left font-semibold px-3 py-2">
              {{ t('snapshots.compare.colFields') }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="c in result.changes"
            :key="`${c.entity}:${c.entity_id}`"
            class="border-t border-border/50"
          >
            <td class="px-3 py-2 font-mono">{{ c.entity }}</td>
            <td class="px-3 py-2 font-mono">#{{ c.entity_id }}</td>
            <td class="px-3 py-2">
              <Badge :tone="statusTone(c.status)">{{ c.status }}</Badge>
            </td>
            <td class="px-3 py-2 text-fg-muted whitespace-nowrap">
              {{ formatDate(c.last_action_at) }}
            </td>
            <td class="px-3 py-2 tabular-nums">{{ c.actions_count }}</td>
            <td class="px-3 py-2 text-xs text-fg-muted font-mono truncate max-w-md">
              {{ c.fields_changed.join(', ') || '—' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <EmptyState
      v-else-if="result"
      :icon="Diff"
      :title="t('snapshots.compare.noChangesTitle')"
      :description="t('snapshots.compare.noChangesDescription')"
      size="sm"
    />

    <EmptyState
      v-else
      :icon="Diff"
      :title="t('snapshots.compare.pickTitle')"
      :description="t('snapshots.compare.pickDescription')"
      size="sm"
    />
  </div>
</template>
