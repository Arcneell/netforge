<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Download,
  Upload,
  CheckCircle2,
  AlertTriangle,
  Info,
  X,
  FileText,
  Archive,
  HelpCircle,
  Wand2,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import Select from '@/components/ui/Select.vue'
import Badge from '@/components/ui/Badge.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import CsvDropzone from '@/components/CsvDropzone.vue'
import CsvMappingAssistant from '@/components/CsvMappingAssistant.vue'
import {
  importsApi,
  IMPORT_ENTITIES,
  type ImportEntity,
  type ImportReport,
  type BulkImportReport,
  type DetectReport,
} from '@/api'
import { useToast } from '@/composables/useToast'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { formatNumber, formatBytes } from '@/utils/formatters'

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

// Tab state: "bulk" is the new default because most users just want to drop
// every CSV they have and let the backend route them. "single" stays for
// power users who want to target a specific entity with a fixed file.
type Mode = 'bulk' | 'single'
const mode = ref<Mode>('bulk')

// --- Single-file mode (legacy flow) --------------------------------------- #

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
    // Use the pending mapping iff it was prepared for THIS entity — keeps
    // a stale mapping from accidentally rewriting a different file's
    // headers when the user switches entities between mapping and upload.
    const mapping =
      pendingMappingEntity.value === entity.value ? pendingMapping.value ?? undefined : undefined
    const result = await importsApi.upload(
      entity.value,
      file.value,
      dryRun.value,
      mapping,
    )
    report.value = result
    lastEntity.value = entity.value
    // Single-shot use — clear so a follow-up import on the same entity
    // doesn't surprise the operator by reusing it.
    if (mapping) {
      pendingMapping.value = null
      pendingMappingEntity.value = null
    }
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
  window.open(`/api/exports/${entity.value}`, '_blank', 'noopener')
}

function downloadAll() {
  // Browser handles the streamed ZIP download. The endpoint accepts any
  // authenticated user — backend is the source of truth for permissions.
  window.open('/api/exports/all', '_blank', 'noopener')
}

const reportTone = computed<'success' | 'warning' | 'danger' | 'primary'>(() => {
  const r = report.value
  if (!r) return 'primary'
  if (r.applied) return 'success'
  if (r.error_rows.length > 0) return 'danger'
  return 'warning'
})

const reportSummary = computed(() => {
  const r = report.value
  if (!r) return ''
  if (r.error_rows.length > 0)
    return t('import.report.partial', { ok: r.ok_rows, total: r.parsed_rows })
  if (r.applied) return t('import.report.successAll', { count: r.ok_rows })
  return t('import.report.successDryRun', { count: r.ok_rows })
})

// --- Bulk mode ------------------------------------------------------------ #

// `(File, DetectReport | "pending" | "failed")` per slot. Detection runs
// client-side as soon as a file lands so the UI can show a route before the
// user even clicks "Run import".
interface BulkSlot {
  file: File
  detection: DetectReport | null
  detecting: boolean
  detectError: string | null
}

const bulkFiles = ref<BulkSlot[]>([])
const bulkDryRun = ref(true)
const bulkSubmitting = ref(false)
const bulkReport = ref<BulkImportReport | null>(null)
const bulkDragOver = ref(false)
const bulkInput = ref<HTMLInputElement | null>(null)

// Same limits as `csv_import.BULK_*` — duplicated client-side to give a
// fast preview before paying the round-trip.
const MAX_FILES = 50
const MAX_TOTAL_BYTES = 50 * 1024 * 1024
const MAX_PER_FILE = 10 * 1024 * 1024

const totalBulkBytes = computed(() => bulkFiles.value.reduce((s, b) => s + b.file.size, 0))

// AI-assisted column mapping modal — opened by the "Need help mapping?"
// button. Always available; the LLM call is admin-only and rate-limited.
const mappingOpen = ref(false)
// When the assistant emits `apply`, we stash the mapping here. The next
// `submit()` forwards it to the backend as `column_map` (server-side
// header rewrite) and then clears the slot so a subsequent import doesn't
// silently keep using stale field translations.
const pendingMapping = ref<Record<string, string | null> | null>(null)
const pendingMappingEntity = ref<ImportEntity | null>(null)

function onMappingApply(mapping: Record<string, string | null>, mappedEntity: ImportEntity) {
  pendingMapping.value = mapping
  pendingMappingEntity.value = mappedEntity
  // Auto-switch the single-import dropdown to the entity the mapping was
  // built for — avoids the surprise of "I mapped for switches but the
  // upload tab is still on sites".
  entity.value = mappedEntity
}

const bulkOverLimit = computed(() => totalBulkBytes.value > MAX_TOTAL_BYTES)

const canSubmitBulk = computed(
  () =>
    bulkFiles.value.length > 0 &&
    !bulkSubmitting.value &&
    !bulkOverLimit.value &&
    bulkFiles.value.every((b) => !b.detecting),
)

function acceptBulkFile(f: File): boolean {
  const lower = f.name.toLowerCase()
  if (!lower.endsWith('.csv') && !lower.endsWith('.zip')) {
    toastError(t('import.errors.bulkNotCsvOrZip'))
    return false
  }
  if (f.size > MAX_PER_FILE) {
    toastError(t('import.errors.tooLarge'))
    return false
  }
  return true
}

async function addBulkFiles(files: FileList | File[]) {
  for (const f of files) {
    if (!acceptBulkFile(f)) continue
    if (bulkFiles.value.length >= MAX_FILES) {
      toastError(t('import.errors.tooManyFiles', { max: MAX_FILES }))
      break
    }
    const slot: BulkSlot = {
      file: f,
      detection: null,
      detecting: false,
      detectError: null,
    }
    bulkFiles.value.push(slot)
    // ZIPs are not detected client-side — we only learn their contents after
    // the server unpacks them. Skip the per-file detection probe.
    if (f.name.toLowerCase().endsWith('.zip')) continue
    detectSlot(slot)
  }
}

async function detectSlot(slot: BulkSlot) {
  slot.detecting = true
  slot.detectError = null
  try {
    slot.detection = await importsApi.detect(slot.file)
  } catch (err) {
    slot.detectError = describe(err)
  } finally {
    slot.detecting = false
  }
}

function removeBulkSlot(idx: number) {
  bulkFiles.value.splice(idx, 1)
}

function clearBulk() {
  bulkFiles.value = []
  bulkReport.value = null
}

function onBulkPickerClick() {
  bulkInput.value?.click()
}

function onBulkInputChange(ev: Event) {
  const target = ev.target as HTMLInputElement
  if (target.files) addBulkFiles(target.files)
  // Reset so the same file can be picked again.
  if (bulkInput.value) bulkInput.value.value = ''
}

function onBulkDrop(ev: DragEvent) {
  ev.preventDefault()
  bulkDragOver.value = false
  if (ev.dataTransfer?.files) addBulkFiles(ev.dataTransfer.files)
}

async function submitBulk() {
  if (!canSubmitBulk.value) return
  bulkSubmitting.value = true
  try {
    const result = await importsApi.uploadBulk(
      bulkFiles.value.map((b) => b.file),
      bulkDryRun.value,
    )
    bulkReport.value = result
    queueMicrotask(() => {
      document.getElementById('bulk-report')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  } catch (err) {
    toastError(describe(err))
  } finally {
    bulkSubmitting.value = false
  }
}

const bulkReportTone = computed<'success' | 'warning' | 'danger' | 'primary'>(() => {
  const r = bulkReport.value
  if (!r) return 'primary'
  if (r.applied) return 'success'
  if (r.files.some((f) => f.error_rows.length > 0)) return 'danger'
  return 'warning'
})

const bulkReportSummary = computed(() => {
  const r = bulkReport.value
  if (!r) return ''
  if (r.files.some((f) => f.error_rows.length > 0))
    return t('import.bulk.report.partial', {
      ok: r.total_ok_rows,
      total: r.total_parsed_rows,
    })
  if (r.applied)
    return t('import.bulk.report.successAll', {
      count: r.total_ok_rows,
      files: r.files.length,
    })
  return t('import.bulk.report.successDryRun', {
    count: r.total_ok_rows,
    files: r.files.length,
  })
})

function entityLabelOrFallback(e: ImportEntity | null): string {
  if (e === null) return t('import.bulk.detected.unknown')
  return t(entityLabel[e])
}
</script>

<template>
  <div class="p-6 max-w-5xl mx-auto">
    <PageHeader :title="t('nav.import')" :subtitle="t('import.subtitle')">
      <template #help>
        <HelpTooltip :text="t('import.help')" placement="bottom" />
      </template>
      <template #actions>
        <Button variant="ghost" @click="mappingOpen = true">
          <Wand2 class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.csvMapping.openButton') }}
        </Button>
        <Button variant="secondary" @click="downloadAll">
          <Download class="w-4 h-4" aria-hidden="true" />
          {{ t('import.downloadAll') }}
        </Button>
      </template>
    </PageHeader>

    <CsvMappingAssistant
      :open="mappingOpen"
      :entity="entity"
      @close="mappingOpen = false"
      @apply="onMappingApply"
    />

    <!-- Visible reminder that a mapping is queued. Same entity gate as the
         `submit()` logic so a stale mapping on a different entity stays
         hidden. -->
    <p
      v-if="pendingMapping && pendingMappingEntity === entity"
      class="text-xs text-primary-700 bg-primary-50 border border-primary-200 rounded p-3 mb-3 flex items-center gap-2"
    >
      <Wand2 class="w-3.5 h-3.5" aria-hidden="true" />
      {{ t('ai.csvMapping.pendingNotice') }}
    </p>

    <!-- Mode tabs -->
    <div
      class="inline-flex items-center gap-1 p-1 bg-muted rounded-md mb-5"
      role="tablist"
      :aria-label="t('import.modeAria')"
    >
      <button
        type="button"
        role="tab"
        :aria-selected="mode === 'bulk'"
        class="px-3 py-1.5 text-sm font-medium rounded transition"
        :class="mode === 'bulk' ? 'bg-surface text-fg shadow-sm' : 'text-fg-muted hover:text-fg'"
        @click="mode = 'bulk'"
      >
        {{ t('import.tabs.bulk') }}
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="mode === 'single'"
        class="px-3 py-1.5 text-sm font-medium rounded transition"
        :class="mode === 'single' ? 'bg-surface text-fg shadow-sm' : 'text-fg-muted hover:text-fg'"
        @click="mode = 'single'"
      >
        {{ t('import.tabs.single') }}
      </button>
    </div>

    <!-- =================== BULK MODE =================== -->
    <div v-if="mode === 'bulk'" class="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
      <section class="nf-card p-5 space-y-5">
        <div>
          <h2 class="text-sm font-semibold text-fg mb-1">{{ t('import.bulk.title') }}</h2>
          <p class="text-xs text-fg-muted">{{ t('import.bulk.subtitle') }}</p>
        </div>

        <!-- Dropzone -->
        <div
          role="button"
          tabindex="0"
          :aria-disabled="bulkSubmitting"
          class="flex flex-col items-center justify-center gap-2 px-4 py-8 border-2 border-dashed rounded-md text-center transition cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/60"
          :class="[
            bulkDragOver
              ? 'border-primary-500 bg-primary-50/60 dark:bg-primary-900/20'
              : 'border-border hover:border-primary-400 hover:bg-surface-hover',
            bulkSubmitting ? 'opacity-50 pointer-events-none' : '',
          ]"
          @click="onBulkPickerClick"
          @keydown.enter.prevent="onBulkPickerClick"
          @keydown.space.prevent="onBulkPickerClick"
          @dragenter.prevent="bulkDragOver = true"
          @dragover.prevent="bulkDragOver = true"
          @dragleave.prevent="bulkDragOver = false"
          @drop="onBulkDrop"
        >
          <Upload class="w-7 h-7 text-fg-muted" aria-hidden="true" />
          <p class="text-sm text-fg">{{ t('import.bulk.dropPrompt') }}</p>
          <p class="text-xs text-fg-muted">{{ t('import.bulk.dropHint') }}</p>
          <input
            ref="bulkInput"
            type="file"
            class="sr-only"
            accept=".csv,.zip,text/csv,application/zip"
            multiple
            @change="onBulkInputChange"
          />
        </div>

        <!-- File list with detection results -->
        <ul v-if="bulkFiles.length > 0" class="space-y-2">
          <li
            v-for="(slot, i) in bulkFiles"
            :key="i"
            class="flex items-center gap-3 px-3 py-2 border border-border rounded-md bg-surface"
          >
            <Archive
              v-if="slot.file.name.toLowerCase().endsWith('.zip')"
              class="w-5 h-5 text-primary-600 dark:text-primary-400 flex-shrink-0"
              aria-hidden="true"
            />
            <FileText
              v-else
              class="w-5 h-5 text-primary-600 dark:text-primary-400 flex-shrink-0"
              aria-hidden="true"
            />
            <div class="min-w-0 flex-1">
              <p class="text-sm text-fg truncate font-medium">{{ slot.file.name }}</p>
              <p class="text-xs text-fg-muted font-mono">
                {{ formatBytes(slot.file.size) }}
              </p>
            </div>

            <!-- Detection badge -->
            <span v-if="slot.detecting" class="text-xs text-fg-muted">
              {{ t('import.bulk.detected.detecting') }}
            </span>
            <Badge
              v-else-if="slot.file.name.toLowerCase().endsWith('.zip')"
              tone="primary"
              size="sm"
            >
              {{ t('import.bulk.detected.zip') }}
            </Badge>
            <Badge v-else-if="slot.detection?.entity" tone="success" size="sm">
              → {{ entityLabelOrFallback(slot.detection.entity) }}
            </Badge>
            <Badge
              v-else-if="slot.detection && slot.detection.entity === null"
              tone="danger"
              size="sm"
            >
              <HelpCircle class="w-3 h-3" aria-hidden="true" />
              {{ t('import.bulk.detected.unknown') }}
            </Badge>
            <Badge v-else-if="slot.detectError" tone="danger" size="sm">
              {{ t('import.bulk.detected.error') }}
            </Badge>

            <Button
              variant="ghost"
              size="sm"
              :disabled="bulkSubmitting"
              :aria-label="t('import.bulk.removeFile')"
              @click="removeBulkSlot(i)"
            >
              <X class="w-4 h-4" aria-hidden="true" />
            </Button>
          </li>
        </ul>

        <!-- Total size -->
        <div
          v-if="bulkFiles.length > 0"
          class="flex items-center justify-between text-xs"
          :class="bulkOverLimit ? 'text-danger' : 'text-fg-muted'"
        >
          <span>
            {{
              t('import.bulk.totalSize', {
                size: formatBytes(totalBulkBytes),
                files: bulkFiles.length,
              })
            }}
          </span>
          <span v-if="bulkOverLimit">
            {{ t('import.bulk.totalOverLimit', { max: formatBytes(MAX_TOTAL_BYTES) }) }}
          </span>
        </div>

        <label class="flex items-start gap-2 cursor-pointer">
          <input
            v-model="bulkDryRun"
            type="checkbox"
            class="mt-0.5 h-4 w-4 rounded border-border text-primary-600 focus:ring-primary-500"
          />
          <span class="text-sm">
            <span class="text-fg font-medium">{{ t('import.dryRun') }}</span>
            <span class="block text-xs text-fg-muted">{{ t('import.bulk.dryRunHint') }}</span>
          </span>
        </label>

        <div class="flex flex-wrap items-center gap-2 pt-2 border-t border-border">
          <Button
            variant="primary"
            :loading="bulkSubmitting"
            :disabled="!canSubmitBulk"
            @click="submitBulk"
          >
            <Upload class="w-4 h-4" aria-hidden="true" />
            {{ bulkDryRun ? t('import.bulk.submitDryRun') : t('import.bulk.submit') }}
          </Button>
          <Button
            v-if="bulkFiles.length > 0"
            variant="secondary"
            :disabled="bulkSubmitting"
            @click="clearBulk"
          >
            {{ t('import.bulk.clearAll') }}
          </Button>
        </div>
      </section>

      <!-- Help -->
      <aside class="nf-card p-5">
        <h2 class="text-sm font-semibold text-fg flex items-center gap-2">
          <Info class="w-4 h-4 text-primary-600 dark:text-primary-400" aria-hidden="true" />
          {{ t('import.bulk.helpTitle') }}
        </h2>
        <ul class="mt-2 space-y-1.5 text-xs text-fg-muted list-disc pl-4">
          <li>{{ t('import.bulk.helpDetect') }}</li>
          <li>{{ t('import.bulk.helpOrder') }}</li>
          <li>{{ t('import.bulk.helpTransaction') }}</li>
          <li>{{ t('import.bulk.helpZip') }}</li>
        </ul>
      </aside>
    </div>

    <!-- =================== SINGLE MODE (legacy) =================== -->
    <div v-else class="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
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

    <!-- Bulk report -->
    <section
      v-if="bulkReport && mode === 'bulk'"
      id="bulk-report"
      class="nf-card mt-6 overflow-hidden"
      aria-live="polite"
    >
      <div class="p-5 border-b border-border">
        <div class="flex items-center gap-3 flex-wrap">
          <CheckCircle2
            v-if="bulkReportTone === 'success'"
            class="w-5 h-5 text-success"
            aria-hidden="true"
          />
          <AlertTriangle
            v-else-if="bulkReportTone === 'danger'"
            class="w-5 h-5 text-danger"
            aria-hidden="true"
          />
          <Info v-else class="w-5 h-5 text-warning" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <p class="text-sm font-semibold text-fg">{{ t('import.bulk.report.title') }}</p>
            <p class="text-xs text-fg-muted">{{ bulkReportSummary }}</p>
          </div>
          <Badge :tone="bulkReport.applied ? 'success' : 'muted'">
            {{
              bulkReport.applied ? t('import.report.appliedTrue') : t('import.report.appliedFalse')
            }}
          </Badge>
        </div>

        <dl class="grid grid-cols-3 gap-4 mt-4">
          <div>
            <dt class="text-xs text-fg-muted">{{ t('import.bulk.report.files') }}</dt>
            <dd class="text-2xl font-semibold text-fg font-mono tabular-nums">
              {{ formatNumber(bulkReport.files.length) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-fg-muted">{{ t('import.report.okRows') }}</dt>
            <dd class="text-2xl font-semibold text-success font-mono tabular-nums">
              {{ formatNumber(bulkReport.total_ok_rows) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-fg-muted">{{ t('import.report.parsedRows') }}</dt>
            <dd class="text-2xl font-semibold text-fg font-mono tabular-nums">
              {{ formatNumber(bulkReport.total_parsed_rows) }}
            </dd>
          </div>
        </dl>
      </div>

      <!-- Per-file rows -->
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-muted text-fg-muted text-xs uppercase tracking-wide">
            <tr>
              <th class="text-left px-3 py-2 font-medium">
                {{ t('import.bulk.report.columns.file') }}
              </th>
              <th class="text-left px-3 py-2 font-medium">
                {{ t('import.bulk.report.columns.entity') }}
              </th>
              <th class="text-right px-3 py-2 w-24 font-medium">{{ t('import.report.okRows') }}</th>
              <th class="text-right px-3 py-2 w-24 font-medium">
                {{ t('import.report.errorRows') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(fileReport, i) in bulkReport.files"
              :key="i"
              class="border-t border-border align-top"
            >
              <td class="px-3 py-2 font-mono text-fg break-all">{{ fileReport.filename }}</td>
              <td class="px-3 py-2">
                <Badge v-if="fileReport.detected_entity" tone="primary" size="sm">
                  {{ entityLabelOrFallback(fileReport.detected_entity) }}
                </Badge>
                <Badge v-else tone="danger" size="sm">
                  {{ t('import.bulk.detected.unknown') }}
                </Badge>
              </td>
              <td
                class="px-3 py-2 text-right font-mono"
                :class="fileReport.ok_rows > 0 ? 'text-success' : 'text-fg-muted'"
              >
                {{ formatNumber(fileReport.ok_rows) }}
              </td>
              <td
                class="px-3 py-2 text-right font-mono"
                :class="fileReport.error_rows.length > 0 ? 'text-danger' : 'text-fg-muted'"
              >
                {{ formatNumber(fileReport.error_rows.length) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Per-file error details -->
      <template v-for="(fileReport, i) in bulkReport.files" :key="`err-${i}`">
        <div v-if="fileReport.error_rows.length > 0" class="border-t border-border bg-danger/5">
          <div class="px-5 py-2 text-xs font-medium text-fg-muted">
            <span class="font-mono text-fg">{{ fileReport.filename }}</span>
            <span>·</span>
            <span>{{ t('import.report.errorsTitle') }} ({{ fileReport.error_rows.length }})</span>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead class="bg-muted text-fg-muted text-xs uppercase tracking-wide">
                <tr>
                  <th class="text-right px-3 py-1.5 w-16 font-medium">
                    {{ t('import.report.columns.line') }}
                  </th>
                  <th class="text-left px-3 py-1.5 w-32 font-medium">
                    {{ t('import.report.columns.column') }}
                  </th>
                  <th class="text-left px-3 py-1.5 w-40 font-medium">
                    {{ t('import.report.columns.value') }}
                  </th>
                  <th class="text-left px-3 py-1.5 font-medium">
                    {{ t('import.report.columns.error') }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(err, j) in fileReport.error_rows"
                  :key="j"
                  class="border-t border-border align-top"
                >
                  <td class="px-3 py-1.5 text-right font-mono text-fg-muted">{{ err.line }}</td>
                  <td class="px-3 py-1.5 font-mono text-fg">{{ err.column || '—' }}</td>
                  <td class="px-3 py-1.5 font-mono text-fg break-all">
                    <span v-if="err.value">{{ err.value }}</span>
                    <span v-else class="text-fg-muted">—</span>
                  </td>
                  <td class="px-3 py-1.5 text-fg">{{ err.error }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </section>

    <!-- Single-mode report (unchanged) -->
    <section
      v-if="report && mode === 'single'"
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
