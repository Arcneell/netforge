<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Download, Upload, CheckCircle2, AlertTriangle, Info } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import Select from '@/components/ui/Select.vue'
import Badge from '@/components/ui/Badge.vue'
import CsvDropzone from '@/components/CsvDropzone.vue'
import { importsApi, IMPORT_ENTITIES, type ImportEntity, type ImportReport } from '@/api'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { formatNumber } from '@/utils/formatters'

const { t } = useI18n()
const { error: toastError } = useToast()
const { describe } = useApiErrorMessage()

// Recommended import order — sites first, links last. IPs come BEFORE ports
// because `_persist_port` resolves `connected_ip` via the Ip table and errors
// out if the IP doesn't exist yet; round-tripping a CSV with port→IP
// associations on a fresh restore requires this ordering.
const ORDERED: ImportEntity[] = [
  'sites',
  'rooms',
  'vlans',
  'subnets',
  'devices',
  'switches',
  'ips',
  'ports',
  'links',
]

const entityLabel: Record<ImportEntity, string> = {
  sites: 'site.labelPlural',
  rooms: 'room.labelPlural',
  vlans: 'vlan.labelPlural',
  subnets: 'subnet.labelPlural',
  ips: 'ip.labelPlural',
  devices: 'device.labelPlural',
  switches: 'switch.labelPlural',
  ports: 'port.labelPlural',
  links: 'nav.topology', // closest existing key — links aren't a top-level nav item
}

const entity = ref<ImportEntity>('sites')
const file = ref<File | null>(null)
const dryRun = ref(true)
const submitting = ref(false)
const report = ref<ImportReport | null>(null)
const lastEntity = ref<ImportEntity | null>(null)

const entityOptions = computed(() =>
  IMPORT_ENTITIES.map((e) => ({ value: e, label: t(entityLabel[e]) })),
)

function onReject(reason: 'notCsv' | 'tooLarge') {
  toastError(t(`import.errors.${reason}`))
}

async function submit() {
  if (!file.value || submitting.value) return
  submitting.value = true
  try {
    const result = await importsApi.upload(entity.value, file.value, dryRun.value)
    report.value = result
    lastEntity.value = entity.value
    // Scroll the report into view on small viewports — it lives below the form.
    queueMicrotask(() => {
      document
        .getElementById('import-report')
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  } catch (err) {
    toastError(describe(err))
  } finally {
    submitting.value = false
  }
}

function downloadTemplate() {
  // The export endpoint streams the entity's current rows in the exact format
  // the importer expects — perfect as a "starter template" or for round-trips.
  window.open(`/api/exports/${entity.value}`, '_blank', 'noopener')
}

// --- Report helpers ------------------------------------------------------- #

const reportTone = computed<'success' | 'warning' | 'danger' | 'primary'>(() => {
  const r = report.value
  if (!r) return 'primary'
  if (r.applied) return 'success'
  if (r.error_rows.length > 0) return 'danger'
  return 'warning' // dry-run with no errors → ready to apply
})

const reportSummary = computed(() => {
  const r = report.value
  if (!r) return ''
  if (r.error_rows.length > 0)
    return t('import.report.partial', { ok: r.ok_rows, total: r.parsed_rows })
  if (r.applied) return t('import.report.successAll', { count: r.ok_rows })
  return t('import.report.successDryRun', { count: r.ok_rows })
})
</script>

<template>
  <div class="p-6 max-w-5xl mx-auto">
    <PageHeader :title="t('nav.import')" :subtitle="t('import.subtitle')" />

    <div class="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
      <!-- Form -->
      <section class="nf-card p-5 space-y-5">
        <div>
          <label class="block text-sm font-medium text-fg mb-1.5">{{ t('import.entity') }}</label>
          <Select
            :model-value="entity"
            :options="entityOptions"
            @update:model-value="(v) => (entity = v as ImportEntity)"
          />
          <p class="text-xs text-fg-muted mt-1.5">{{ t('import.entityHint') }}</p>
        </div>

        <div>
          <label class="block text-sm font-medium text-fg mb-1.5">{{ t('import.file') }}</label>
          <CsvDropzone
            :model-value="file"
            :disabled="submitting"
            @update:model-value="(f) => (file = f)"
            @reject="onReject"
          />
        </div>

        <label class="flex items-start gap-2 cursor-pointer">
          <input
            v-model="dryRun"
            type="checkbox"
            class="mt-0.5 h-4 w-4 rounded border-border text-primary-600 focus:ring-primary-500"
          />
          <span class="text-sm">
            <span class="text-fg font-medium">{{ t('import.dryRun') }}</span>
            <span class="block text-xs text-fg-muted">{{ t('import.dryRunHint') }}</span>
          </span>
        </label>

        <div class="flex flex-wrap items-center gap-2 pt-2 border-t border-border">
          <Button variant="primary" :loading="submitting" :disabled="!file" @click="submit">
            <Upload class="w-4 h-4" aria-hidden="true" />
            {{ dryRun ? t('import.submitDryRun') : t('import.submit') }}
          </Button>
          <Button variant="secondary" :disabled="submitting" @click="downloadTemplate">
            <Download class="w-4 h-4" aria-hidden="true" />
            {{ t('import.exportTemplate') }}
          </Button>
        </div>
        <p class="text-xs text-fg-muted -mt-3">{{ t('import.exportTemplateHint') }}</p>
      </section>

      <!-- Order guidance -->
      <aside class="nf-card p-5">
        <h2 class="text-sm font-semibold text-fg flex items-center gap-2">
          <Info class="w-4 h-4 text-primary-600 dark:text-primary-400" aria-hidden="true" />
          {{ t('import.orderTitle') }}
        </h2>
        <p class="text-xs text-fg-muted mt-1.5 mb-3">{{ t('import.orderHint') }}</p>
        <ol class="space-y-1.5 text-sm">
          <li
            v-for="(e, i) in ORDERED"
            :key="e"
            class="flex items-center gap-2 px-2 py-1 rounded transition cursor-pointer"
            :class="
              entity === e
                ? 'bg-primary-100 text-primary-700 dark:bg-primary-900/40 dark:text-primary-300'
                : 'text-fg hover:bg-surface-hover'
            "
            @click="entity = e"
          >
            <span class="font-mono text-xs text-fg-muted w-5 text-right">{{ i + 1 }}.</span>
            <span class="font-medium">{{ t(entityLabel[e]) }}</span>
          </li>
        </ol>
      </aside>
    </div>

    <!-- Report -->
    <section
      v-if="report"
      id="import-report"
      class="nf-card mt-6 overflow-hidden"
      aria-live="polite"
    >
      <div class="p-5 border-b border-border">
        <div class="flex items-center gap-3 flex-wrap">
          <CheckCircle2
            v-if="reportTone === 'success'"
            class="w-5 h-5 text-success"
            aria-hidden="true"
          />
          <AlertTriangle
            v-else-if="reportTone === 'danger'"
            class="w-5 h-5 text-danger"
            aria-hidden="true"
          />
          <Info v-else class="w-5 h-5 text-warning" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <p class="text-sm font-semibold text-fg">{{ t('import.report.title') }}</p>
            <p class="text-xs text-fg-muted">
              <span v-if="lastEntity">{{ t(entityLabel[lastEntity]) }} ·</span>
              {{ reportSummary }}
            </p>
          </div>
          <Badge :tone="report.applied ? 'success' : 'muted'">
            {{ report.applied ? t('import.report.appliedTrue') : t('import.report.appliedFalse') }}
          </Badge>
        </div>

        <dl class="grid grid-cols-3 gap-4 mt-4">
          <div>
            <dt class="text-xs text-fg-muted">{{ t('import.report.parsedRows') }}</dt>
            <dd class="text-2xl font-semibold text-fg font-mono tabular-nums">
              {{ formatNumber(report.parsed_rows) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-fg-muted">{{ t('import.report.okRows') }}</dt>
            <dd class="text-2xl font-semibold text-success font-mono tabular-nums">
              {{ formatNumber(report.ok_rows) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-fg-muted">{{ t('import.report.errorRows') }}</dt>
            <dd
              class="text-2xl font-semibold font-mono tabular-nums"
              :class="report.error_rows.length > 0 ? 'text-danger' : 'text-fg-muted'"
            >
              {{ formatNumber(report.error_rows.length) }}
            </dd>
          </div>
        </dl>
      </div>

      <div v-if="report.error_rows.length > 0" class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-muted text-fg-muted text-xs uppercase tracking-wide">
            <tr>
              <th class="text-right px-3 py-2 w-16 font-medium">
                {{ t('import.report.columns.line') }}
              </th>
              <th class="text-left px-3 py-2 w-32 font-medium">
                {{ t('import.report.columns.column') }}
              </th>
              <th class="text-left px-3 py-2 w-40 font-medium">
                {{ t('import.report.columns.value') }}
              </th>
              <th class="text-left px-3 py-2 font-medium">
                {{ t('import.report.columns.error') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(err, i) in report.error_rows"
              :key="i"
              class="border-t border-border align-top"
            >
              <td class="px-3 py-2 text-right font-mono text-fg-muted">{{ err.line }}</td>
              <td class="px-3 py-2 font-mono text-fg">{{ err.column || '—' }}</td>
              <td class="px-3 py-2 font-mono text-fg break-all">
                <span v-if="err.value">{{ err.value }}</span>
                <span v-else class="text-fg-muted">—</span>
              </td>
              <td class="px-3 py-2 text-fg">{{ err.error }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="px-5 py-4 text-sm text-fg-muted">{{ t('import.report.noErrors') }}</p>
    </section>
  </div>
</template>
