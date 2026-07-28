<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Download,
  Upload,
  UploadCloud,
  CheckCircle2,
  AlertTriangle,
  Info,
  X,
  FileText,
  Archive,
  HelpCircle,
  Wand2,
  Check,
  ArrowRight,
} from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import Select from '@/components/ui/Select.vue'
import Badge from '@/components/ui/Badge.vue'
import Segmented, { type SegmentedOption } from '@/components/ui/Segmented.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import EmptyState from '@/components/EmptyState.vue'
import CsvDropzone from '@/components/CsvDropzone.vue'
import CsvMappingAssistant from '@/components/CsvMappingAssistant.vue'
import {
  importsApi,
  IMPORT_ENTITIES,
  type ImportEntity,
  type ImportErrorRow,
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
      pendingMappingEntity.value === entity.value ? (pendingMapping.value ?? undefined) : undefined
    const result = await importsApi.upload(entity.value, file.value, dryRun.value, mapping)
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

// --- Progress rail --------------------------------------------------------- #
// The import is a four-beat sequence — pick, dry-run, review, apply — and it
// runs identically in both modes. Everything below derives the operator's
// position in that sequence from whichever mode is on screen, so the rail
// never contradicts the panel underneath it.

const modeOptions = computed<SegmentedOption<Mode>[]>(() => [
  { value: 'bulk', label: t('import.tabs.bulk'), count: bulkFiles.value.length || undefined },
  { value: 'single', label: t('import.tabs.single') },
])

const activeReport = computed<ImportReport | BulkImportReport | null>(() =>
  mode.value === 'bulk' ? bulkReport.value : report.value,
)

const hasPickedFiles = computed(() =>
  mode.value === 'bulk' ? bulkFiles.value.length > 0 : !!file.value,
)

const activeErrorCount = computed(() => {
  const r = activeReport.value
  if (!r) return 0
  return 'files' in r ? r.files.reduce((s, f) => s + f.error_rows.length, 0) : r.error_rows.length
})

const activeApplied = computed(() => !!activeReport.value?.applied)

const currentStep = computed(() => {
  if (!hasPickedFiles.value) return 1
  if (!activeReport.value) return 2
  if (activeErrorCount.value > 0) return 3
  return 4
})

const steps = computed(() => [
  { n: 1, title: t('import.steps.selectTitle'), hint: t('import.steps.selectHint') },
  { n: 2, title: t('import.steps.validateTitle'), hint: t('import.steps.validateHint') },
  { n: 3, title: t('import.steps.reviewTitle'), hint: t('import.steps.reviewHint') },
  { n: 4, title: t('import.steps.applyTitle'), hint: t('import.steps.applyHint') },
])

type StepState = 'done' | 'current' | 'todo'

function stepState(n: number): StepState {
  if (activeApplied.value) return 'done'
  if (n < currentStep.value) return 'done'
  if (n === currentStep.value) return 'current'
  return 'todo'
}

function stepBadgeClass(state: StepState): string {
  if (state === 'done') return 'bg-success/10 text-success'
  if (state === 'current')
    return 'bg-primary-500/15 text-primary-700 dark:text-primary-300 ring-1 ring-inset ring-primary-500/40'
  return 'bg-muted text-fg-subtle'
}

function stepStateLabel(state: StepState): string {
  if (state === 'done') return t('import.steps.done')
  if (state === 'current') return t('import.steps.current')
  return t('import.steps.todo')
}

// Sentence telling the operator what to do next, derived from the report that
// is actually on screen.
const nextStepMessage = computed(() => {
  const r = activeReport.value
  if (!r) return ''
  if (r.applied) return t('import.report.nextStepDone')
  if (activeErrorCount.value > 0) return t('import.report.nextStepFix')
  return t('import.report.nextStepApply')
})

// --- Error triage ---------------------------------------------------------- #
// A 400-row failure is unusable as a flat dump. One filter narrows every error
// table on the page (single mode and each bulk file) to the lines that mention
// a column, a value or a message.

const errorQuery = ref('')

function filterErrors(rows: ImportErrorRow[]): ImportErrorRow[] {
  const q = errorQuery.value.trim().toLowerCase()
  if (!q) return rows
  return rows.filter(
    (e) =>
      String(e.line).includes(q) ||
      (e.column ?? '').toLowerCase().includes(q) ||
      (e.value ?? '').toLowerCase().includes(q) ||
      e.error.toLowerCase().includes(q),
  )
}

// Bulk mode groups errors per file, so "no match" is only true when every
// file's filtered list came back empty.
const bulkNoErrorMatch = computed(() => {
  const r = bulkReport.value
  if (!r || !errorQuery.value.trim() || activeErrorCount.value === 0) return false
  return !r.files.some((f) => filterErrors(f.error_rows).length > 0)
})
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="t('nav.import')" :subtitle="t('import.subtitle')">
      <template #help>
        <HelpTooltip :text="t('import.help')" placement="bottom" />
      </template>
      <template #actions>
        <div class="inline-flex items-center gap-1">
          <Button variant="ghost" @click="mappingOpen = true">
            <Wand2 class="w-4 h-4" aria-hidden="true" />
            {{ t('ai.csvMapping.openButton') }}
          </Button>
          <HelpTooltip :text="t('import.helpMapping')" />
        </div>
        <div class="inline-flex items-center gap-1">
          <Button variant="secondary" @click="downloadAll">
            <Download class="w-4 h-4" aria-hidden="true" />
            {{ t('import.downloadAll') }}
          </Button>
          <HelpTooltip :text="t('import.helpDownloadAll')" />
        </div>
      </template>
    </PageHeader>

    <!-- Where you are in the job. Four beats, same in both modes. -->
    <ol
      class="nf-card p-4 sm:p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 lg:gap-0"
      :aria-label="t('import.steps.aria')"
    >
      <li
        v-for="(s, i) in steps"
        :key="s.n"
        class="flex items-start gap-3 min-w-0"
        :class="i > 0 ? 'lg:border-l lg:border-border lg:pl-5' : 'lg:pr-5'"
        :aria-current="stepState(s.n) === 'current' ? 'step' : undefined"
      >
        <span
          class="inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-semibold tabular-nums flex-shrink-0 mt-0.5 transition-colors duration-150 ease-soft"
          :class="stepBadgeClass(stepState(s.n))"
        >
          <Check v-if="stepState(s.n) === 'done'" class="w-3.5 h-3.5" aria-hidden="true" />
          <template v-else>{{ s.n }}</template>
        </span>
        <div class="min-w-0">
          <p
            class="text-base font-medium"
            :class="stepState(s.n) === 'todo' ? 'text-fg-muted' : 'text-fg'"
          >
            {{ s.title }}
            <span class="sr-only">— {{ stepStateLabel(stepState(s.n)) }}</span>
          </p>
          <p class="text-xs text-fg-muted mt-0.5">{{ s.hint }}</p>
        </div>
      </li>
    </ol>

    <!-- Mode switch + the reminder that an AI mapping is queued. Same entity
         gate as the `submit()` logic so a stale mapping on a different entity
         stays hidden. -->
    <div class="mb-6 flex flex-wrap items-center gap-3">
      <Segmented
        v-model="mode"
        :options="modeOptions"
        :aria-label="t('import.modeAria')"
        class="flex-shrink-0"
      />
      <p
        v-if="pendingMapping && pendingMappingEntity === entity"
        class="inline-flex items-center gap-2 text-xs text-primary-700 dark:text-primary-300 bg-primary-500/10 border border-primary-500/30 rounded-md px-3 py-1.5"
      >
        <Wand2 class="w-3.5 h-3.5 flex-shrink-0" aria-hidden="true" />
        {{ t('ai.csvMapping.pendingNotice') }}
      </p>
    </div>

    <!-- =================== BULK MODE =================== -->
    <div v-if="mode === 'bulk'" class="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6 mb-6">
      <section class="nf-card p-4 sm:p-5 space-y-5">
        <div>
          <h2 class="nf-section-title">{{ t('import.bulk.title') }}</h2>
          <p class="text-sm text-fg-muted mt-0.5">{{ t('import.bulk.subtitle') }}</p>
        </div>

        <!-- Dropzone -->
        <div
          role="button"
          tabindex="0"
          :aria-disabled="bulkSubmitting"
          class="flex flex-col items-center justify-center gap-3 px-6 py-10 rounded-lg border-2 border-dashed text-center cursor-pointer focus:outline-none focus-visible:shadow-ring transition-colors duration-150 ease-soft"
          :class="[
            bulkDragOver
              ? 'border-primary-500 bg-primary-500/10'
              : 'border-border-strong bg-muted/40 hover:border-primary-400 hover:bg-surface-hover',
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
          <span
            class="inline-flex items-center justify-center w-11 h-11 rounded-lg border bg-surface transition-colors duration-150 ease-soft"
            :class="
              bulkDragOver
                ? 'border-primary-500 text-primary-600 dark:text-primary-400'
                : 'border-border text-fg-muted'
            "
          >
            <UploadCloud class="w-5 h-5" :stroke-width="1.75" aria-hidden="true" />
          </span>
          <div class="space-y-1">
            <p class="text-base font-medium text-fg">
              {{ bulkDragOver ? t('import.fileDropNow') : t('import.bulk.dropPrompt') }}
            </p>
            <p class="text-xs text-fg-muted">{{ t('import.bulk.dropHint') }}</p>
          </div>
          <span class="nf-link text-sm font-medium">{{ t('import.fileBrowse') }}</span>
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
        <div v-if="bulkFiles.length > 0">
          <div class="flex items-center justify-between gap-3 mb-2">
            <p class="nf-label">{{ t('import.bulk.filesTitle') }}</p>
            <p
              class="text-xs tabular-nums"
              :class="bulkOverLimit ? 'text-danger' : 'text-fg-muted'"
            >
              {{
                t('import.bulk.totalSize', {
                  size: formatBytes(totalBulkBytes),
                  files: bulkFiles.length,
                })
              }}
              <span v-if="bulkOverLimit">
                · {{ t('import.bulk.totalOverLimit', { max: formatBytes(MAX_TOTAL_BYTES) }) }}
              </span>
            </p>
          </div>
          <ul class="rounded-lg border border-border overflow-hidden divide-y divide-border">
            <li
              v-for="(slot, i) in bulkFiles"
              :key="i"
              class="flex items-center gap-3 px-3 py-2.5 bg-surface transition-colors duration-150 ease-soft hover:bg-surface-hover"
            >
              <span
                class="inline-flex items-center justify-center w-8 h-8 rounded-md bg-primary-500/10 text-primary-600 dark:text-primary-400 flex-shrink-0"
              >
                <Archive
                  v-if="slot.file.name.toLowerCase().endsWith('.zip')"
                  class="w-4 h-4"
                  aria-hidden="true"
                />
                <FileText v-else class="w-4 h-4" aria-hidden="true" />
              </span>
              <div class="min-w-0 flex-1">
                <p class="text-base text-fg truncate font-medium">{{ slot.file.name }}</p>
                <p class="text-xs text-fg-muted font-mono tabular-nums">
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
        </div>

        <!-- HelpTooltip lives OUTSIDE the <label> so clicking `?` doesn't also
             toggle the checkbox via the label's default activation behaviour
             (which would silently flip a validation-only run into a write
             run, or vice versa). Codex P1 on #71. -->
        <div class="flex items-start gap-3 p-3 rounded-lg border border-border bg-muted/40">
          <label class="flex items-start gap-2.5 cursor-pointer flex-1">
            <input
              v-model="bulkDryRun"
              type="checkbox"
              class="mt-0.5 h-4 w-4 rounded border-border-strong accent-primary-600"
            />
            <span>
              <span class="block text-base text-fg font-medium">{{ t('import.dryRun') }}</span>
              <span class="block text-xs text-fg-muted mt-0.5">
                {{ t('import.bulk.dryRunHint') }}
              </span>
            </span>
          </label>
          <HelpTooltip :text="t('import.helpDryRun')" class="mt-0.5" />
        </div>

        <div class="flex flex-wrap items-center gap-2 pt-1">
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
      <aside class="nf-card p-4 sm:p-5 h-fit">
        <h2 class="nf-section-title flex items-center gap-2">
          <Info class="w-4 h-4 text-primary-600 dark:text-primary-400" aria-hidden="true" />
          {{ t('import.bulk.helpTitle') }}
        </h2>
        <ul class="mt-3 space-y-2 text-sm text-fg-muted">
          <li
            v-for="key in ['helpDetect', 'helpOrder', 'helpTransaction', 'helpZip']"
            :key="key"
            class="flex items-start gap-2"
          >
            <span
              class="mt-1.5 w-1 h-1 rounded-full bg-fg-subtle flex-shrink-0"
              aria-hidden="true"
            />
            <span>{{ t(`import.bulk.${key}`) }}</span>
          </li>
        </ul>
      </aside>
    </div>

    <!-- =================== SINGLE MODE (legacy) =================== -->
    <div v-else class="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6 mb-6">
      <section class="nf-card p-4 sm:p-5 space-y-5">
        <div>
          <div class="nf-label mb-1.5 flex items-center gap-1.5">
            <label for="import-entity">{{ t('import.entity') }}</label>
            <HelpTooltip :text="t('import.helpEntity')" />
          </div>
          <Select
            id="import-entity"
            :model-value="entity"
            :options="entityOptions"
            @update:model-value="(v) => (entity = v as ImportEntity)"
          />
          <p class="text-xs text-fg-muted mt-1.5">{{ t('import.entityHint') }}</p>
        </div>

        <div>
          <p class="nf-label mb-1.5">{{ t('import.file') }}</p>
          <CsvDropzone
            :model-value="file"
            :disabled="submitting"
            @update:model-value="(f) => (file = f)"
            @reject="onReject"
          />
        </div>

        <div class="flex items-start gap-3 p-3 rounded-lg border border-border bg-muted/40">
          <label class="flex items-start gap-2.5 cursor-pointer flex-1">
            <input
              v-model="dryRun"
              type="checkbox"
              class="mt-0.5 h-4 w-4 rounded border-border-strong accent-primary-600"
            />
            <span>
              <span class="block text-base text-fg font-medium">{{ t('import.dryRun') }}</span>
              <span class="block text-xs text-fg-muted mt-0.5">{{ t('import.dryRunHint') }}</span>
            </span>
          </label>
          <HelpTooltip :text="t('import.helpDryRun')" class="mt-0.5" />
        </div>

        <div class="pt-1 space-y-2">
          <div class="flex flex-wrap items-center gap-2">
            <Button variant="primary" :loading="submitting" :disabled="!file" @click="submit">
              <Upload class="w-4 h-4" aria-hidden="true" />
              {{ dryRun ? t('import.submitDryRun') : t('import.submit') }}
            </Button>
            <div class="inline-flex items-center gap-1">
              <Button variant="secondary" :disabled="submitting" @click="downloadTemplate">
                <Download class="w-4 h-4" aria-hidden="true" />
                {{ t('import.exportTemplate') }}
              </Button>
              <HelpTooltip :text="t('import.helpExportTemplate')" />
            </div>
          </div>
          <p class="text-xs text-fg-muted">{{ t('import.exportTemplateHint') }}</p>
        </div>
      </section>

      <aside class="nf-card p-4 sm:p-5 h-fit">
        <h2 class="nf-section-title flex items-center gap-2">
          <Info class="w-4 h-4 text-primary-600 dark:text-primary-400" aria-hidden="true" />
          {{ t('import.orderTitle') }}
        </h2>
        <p class="text-xs text-fg-muted mt-1.5 mb-3">{{ t('import.orderHint') }}</p>
        <ol class="space-y-0.5">
          <li v-for="(e, i) in ORDERED" :key="e">
            <button
              type="button"
              class="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-left transition-colors duration-150 ease-soft"
              :class="
                entity === e
                  ? 'bg-primary-500/10 text-primary-700 dark:text-primary-300'
                  : 'text-fg hover:bg-surface-hover'
              "
              :aria-pressed="entity === e"
              @click="entity = e"
            >
              <span class="font-mono text-xs text-fg-subtle w-5 text-right tabular-nums">
                {{ i + 1 }}.
              </span>
              <span class="text-base font-medium">{{ t(entityLabel[e]) }}</span>
            </button>
          </li>
        </ol>
      </aside>
    </div>

    <!-- =================== BULK REPORT =================== -->
    <section
      v-if="bulkReport && mode === 'bulk'"
      id="bulk-report"
      class="nf-card overflow-hidden"
      aria-live="polite"
    >
      <header class="p-4 sm:p-5 border-b border-border">
        <div class="flex items-start gap-3 flex-wrap">
          <CheckCircle2
            v-if="bulkReportTone === 'success'"
            class="w-5 h-5 text-success flex-shrink-0 mt-0.5"
            aria-hidden="true"
          />
          <AlertTriangle
            v-else-if="bulkReportTone === 'danger'"
            class="w-5 h-5 text-danger flex-shrink-0 mt-0.5"
            aria-hidden="true"
          />
          <Info v-else class="w-5 h-5 text-warning flex-shrink-0 mt-0.5" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <h2 class="nf-section-title">{{ t('import.bulk.report.title') }}</h2>
            <p class="text-sm text-fg-muted mt-0.5">{{ bulkReportSummary }}</p>
          </div>
          <Badge :tone="bulkReport.applied ? 'success' : 'muted'" size="md">
            {{
              bulkReport.applied ? t('import.report.appliedTrue') : t('import.report.appliedFalse')
            }}
          </Badge>
        </div>

        <!-- Compact readout — four numbers on one line, not four hero cards. -->
        <div class="mt-4 flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <p class="flex items-baseline gap-1.5">
            <span class="text-lg font-semibold font-mono tabular-nums text-fg">
              {{ formatNumber(bulkReport.files.length) }}
            </span>
            <span class="text-xs text-fg-muted">{{ t('import.bulk.report.files') }}</span>
          </p>
          <p class="flex items-baseline gap-1.5">
            <span class="text-lg font-semibold font-mono tabular-nums text-fg">
              {{ formatNumber(bulkReport.total_parsed_rows) }}
            </span>
            <span class="text-xs text-fg-muted">{{ t('import.report.parsedRows') }}</span>
          </p>
          <p class="flex items-baseline gap-1.5">
            <span class="text-lg font-semibold font-mono tabular-nums text-success">
              {{ formatNumber(bulkReport.total_ok_rows) }}
            </span>
            <span class="text-xs text-fg-muted">{{ t('import.report.okRows') }}</span>
          </p>
          <p class="flex items-baseline gap-1.5">
            <span
              class="text-lg font-semibold font-mono tabular-nums"
              :class="activeErrorCount > 0 ? 'text-danger' : 'text-fg-subtle'"
            >
              {{ formatNumber(activeErrorCount) }}
            </span>
            <span class="text-xs text-fg-muted">{{ t('import.report.errorRows') }}</span>
          </p>
        </div>

        <p
          v-if="nextStepMessage"
          class="mt-4 flex items-start gap-2 rounded-md bg-muted px-3 py-2 text-sm text-fg"
        >
          <ArrowRight class="w-4 h-4 text-fg-subtle flex-shrink-0 mt-0.5" aria-hidden="true" />
          <span>{{ nextStepMessage }}</span>
        </p>
      </header>

      <!-- Per-file rows -->
      <div class="overflow-x-auto">
        <table class="w-full text-base">
          <thead>
            <tr class="border-b border-border">
              <th class="nf-label text-left px-4 sm:px-5 py-2.5">
                {{ t('import.bulk.report.columns.file') }}
              </th>
              <th class="nf-label text-left px-3 py-2.5">
                {{ t('import.bulk.report.columns.entity') }}
              </th>
              <th class="nf-label text-right px-3 py-2.5 w-28">
                {{ t('import.report.okRows') }}
              </th>
              <th class="nf-label text-right px-4 sm:px-5 py-2.5 w-28">
                {{ t('import.report.errorRows') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(fileReport, i) in bulkReport.files"
              :key="i"
              class="border-b border-border last:border-0 align-top"
            >
              <td class="px-4 sm:px-5 py-2.5 font-mono text-sm text-fg break-all">
                {{ fileReport.filename }}
              </td>
              <td class="px-3 py-2.5">
                <Badge v-if="fileReport.detected_entity" tone="primary" size="sm">
                  {{ entityLabelOrFallback(fileReport.detected_entity) }}
                </Badge>
                <Badge v-else tone="danger" size="sm">
                  {{ t('import.bulk.detected.unknown') }}
                </Badge>
              </td>
              <td
                class="px-3 py-2.5 text-right font-mono tabular-nums"
                :class="fileReport.ok_rows > 0 ? 'text-success' : 'text-fg-subtle'"
              >
                {{ formatNumber(fileReport.ok_rows) }}
              </td>
              <td
                class="px-4 sm:px-5 py-2.5 text-right font-mono tabular-nums"
                :class="fileReport.error_rows.length > 0 ? 'text-danger' : 'text-fg-subtle'"
              >
                {{ formatNumber(fileReport.error_rows.length) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Error triage bar — one filter drives every per-file table below. -->
      <div
        v-if="activeErrorCount > 0"
        class="border-t border-border bg-danger/5 px-4 sm:px-5 py-3 flex flex-wrap items-center justify-between gap-3"
      >
        <div class="min-w-0">
          <p class="inline-flex items-center gap-2 text-base font-medium text-danger">
            <AlertTriangle class="w-4 h-4 flex-shrink-0" aria-hidden="true" />
            {{ t('import.report.errorsTitle') }} ({{ formatNumber(activeErrorCount) }})
          </p>
          <p class="text-xs text-fg-muted mt-0.5">{{ t('import.report.errorsHint') }}</p>
        </div>
        <input
          v-if="activeErrorCount > 10"
          v-model="errorQuery"
          type="search"
          class="nf-input nf-input-control w-full sm:w-64"
          :placeholder="t('import.report.errorsFilter')"
          :aria-label="t('import.report.errorsFilter')"
        />
      </div>

      <!-- Per-file error details -->
      <template v-for="(fileReport, i) in bulkReport.files" :key="`err-${i}`">
        <div
          v-if="fileReport.error_rows.length > 0 && filterErrors(fileReport.error_rows).length > 0"
          class="border-t border-border"
        >
          <p class="px-4 sm:px-5 py-2 text-xs text-fg-muted bg-muted/60">
            <span class="font-mono text-fg">{{ fileReport.filename }}</span>
            <span>· {{ formatNumber(filterErrors(fileReport.error_rows).length) }}</span>
          </p>
          <div class="overflow-x-auto">
            <table class="w-full text-base">
              <thead>
                <tr class="border-b border-border">
                  <th class="nf-label text-right px-4 sm:px-5 py-2 w-20">
                    {{ t('import.report.columns.line') }}
                  </th>
                  <th class="nf-label text-left px-3 py-2 w-36">
                    {{ t('import.report.columns.column') }}
                  </th>
                  <th class="nf-label text-left px-3 py-2 w-44">
                    {{ t('import.report.columns.value') }}
                  </th>
                  <th class="nf-label text-left px-4 sm:px-5 py-2">
                    {{ t('import.report.columns.error') }}
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(err, j) in filterErrors(fileReport.error_rows)"
                  :key="j"
                  class="border-b border-border last:border-0 align-top"
                >
                  <td class="px-4 sm:px-5 py-2 text-right">
                    <span class="font-mono text-sm text-fg-muted tabular-nums">{{ err.line }}</span>
                  </td>
                  <td class="px-3 py-2">
                    <Badge v-if="err.column" tone="neutral" monospace>{{ err.column }}</Badge>
                    <span v-else class="text-fg-subtle">—</span>
                  </td>
                  <td class="px-3 py-2 font-mono text-sm text-fg break-all">
                    <span v-if="err.value">{{ err.value }}</span>
                    <span v-else class="text-fg-subtle">—</span>
                  </td>
                  <td class="px-4 sm:px-5 py-2 text-fg">{{ err.error }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>

      <p
        v-if="bulkNoErrorMatch"
        class="border-t border-border px-4 sm:px-5 py-4 text-base text-fg-muted"
      >
        {{ t('import.report.errorsNoMatch') }}
      </p>
    </section>

    <!-- =================== SINGLE-MODE REPORT =================== -->
    <section
      v-else-if="report && mode === 'single'"
      id="import-report"
      class="nf-card overflow-hidden"
      aria-live="polite"
    >
      <header class="p-4 sm:p-5 border-b border-border">
        <div class="flex items-start gap-3 flex-wrap">
          <CheckCircle2
            v-if="reportTone === 'success'"
            class="w-5 h-5 text-success flex-shrink-0 mt-0.5"
            aria-hidden="true"
          />
          <AlertTriangle
            v-else-if="reportTone === 'danger'"
            class="w-5 h-5 text-danger flex-shrink-0 mt-0.5"
            aria-hidden="true"
          />
          <Info v-else class="w-5 h-5 text-warning flex-shrink-0 mt-0.5" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <h2 class="nf-section-title">{{ t('import.report.title') }}</h2>
            <p class="text-sm text-fg-muted mt-0.5">
              <span v-if="lastEntity">{{ t(entityLabel[lastEntity]) }} ·</span>
              {{ reportSummary }}
            </p>
          </div>
          <Badge :tone="report.applied ? 'success' : 'muted'" size="md">
            {{ report.applied ? t('import.report.appliedTrue') : t('import.report.appliedFalse') }}
          </Badge>
        </div>

        <div class="mt-4 flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <p class="flex items-baseline gap-1.5">
            <span class="text-lg font-semibold font-mono tabular-nums text-fg">
              {{ formatNumber(report.parsed_rows) }}
            </span>
            <span class="text-xs text-fg-muted">{{ t('import.report.parsedRows') }}</span>
          </p>
          <p class="flex items-baseline gap-1.5">
            <span class="text-lg font-semibold font-mono tabular-nums text-success">
              {{ formatNumber(report.ok_rows) }}
            </span>
            <span class="text-xs text-fg-muted">{{ t('import.report.okRows') }}</span>
          </p>
          <p class="flex items-baseline gap-1.5">
            <span
              class="text-lg font-semibold font-mono tabular-nums"
              :class="report.error_rows.length > 0 ? 'text-danger' : 'text-fg-subtle'"
            >
              {{ formatNumber(report.error_rows.length) }}
            </span>
            <span class="text-xs text-fg-muted">{{ t('import.report.errorRows') }}</span>
          </p>
        </div>

        <p
          v-if="nextStepMessage"
          class="mt-4 flex items-start gap-2 rounded-md bg-muted px-3 py-2 text-sm text-fg"
        >
          <ArrowRight class="w-4 h-4 text-fg-subtle flex-shrink-0 mt-0.5" aria-hidden="true" />
          <span>{{ nextStepMessage }}</span>
        </p>
      </header>

      <template v-if="report.error_rows.length > 0">
        <div
          class="bg-danger/5 px-4 sm:px-5 py-3 flex flex-wrap items-center justify-between gap-3 border-b border-border"
        >
          <div class="min-w-0">
            <p class="inline-flex items-center gap-2 text-base font-medium text-danger">
              <AlertTriangle class="w-4 h-4 flex-shrink-0" aria-hidden="true" />
              {{ t('import.report.errorsTitle') }} ({{ formatNumber(report.error_rows.length) }})
            </p>
            <p class="text-xs text-fg-muted mt-0.5">{{ t('import.report.errorsHint') }}</p>
          </div>
          <input
            v-if="report.error_rows.length > 10"
            v-model="errorQuery"
            type="search"
            class="nf-input nf-input-control w-full sm:w-64"
            :placeholder="t('import.report.errorsFilter')"
            :aria-label="t('import.report.errorsFilter')"
          />
        </div>

        <div v-if="filterErrors(report.error_rows).length > 0" class="overflow-x-auto">
          <table class="w-full text-base">
            <thead>
              <tr class="border-b border-border">
                <th class="nf-label text-right px-4 sm:px-5 py-2.5 w-20">
                  {{ t('import.report.columns.line') }}
                </th>
                <th class="nf-label text-left px-3 py-2.5 w-36">
                  {{ t('import.report.columns.column') }}
                </th>
                <th class="nf-label text-left px-3 py-2.5 w-44">
                  {{ t('import.report.columns.value') }}
                </th>
                <th class="nf-label text-left px-4 sm:px-5 py-2.5">
                  {{ t('import.report.columns.error') }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(err, i) in filterErrors(report.error_rows)"
                :key="i"
                class="border-b border-border last:border-0 align-top"
              >
                <td class="px-4 sm:px-5 py-2.5 text-right">
                  <span class="font-mono text-sm text-fg-muted tabular-nums">{{ err.line }}</span>
                </td>
                <td class="px-3 py-2.5">
                  <Badge v-if="err.column" tone="neutral" monospace>{{ err.column }}</Badge>
                  <span v-else class="text-fg-subtle">—</span>
                </td>
                <td class="px-3 py-2.5 font-mono text-sm text-fg break-all">
                  <span v-if="err.value">{{ err.value }}</span>
                  <span v-else class="text-fg-subtle">—</span>
                </td>
                <td class="px-4 sm:px-5 py-2.5 text-fg">{{ err.error }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="px-4 sm:px-5 py-4 text-base text-fg-muted">
          {{ t('import.report.errorsNoMatch') }}
        </p>
      </template>

      <p v-else class="px-4 sm:px-5 py-4 text-base text-fg-muted">
        {{ t('import.report.noErrors') }}
      </p>
    </section>

    <!-- Nothing picked and nothing run yet: name the next action instead of
         leaving a gap under the form. -->
    <section v-else-if="!hasPickedFiles" class="nf-card">
      <EmptyState
        :icon="UploadCloud"
        :title="t('import.bulk.emptyTitle')"
        :description="t('import.bulk.emptyDescription')"
        size="sm"
      />
    </section>

    <CsvMappingAssistant
      :open="mappingOpen"
      :entity="entity"
      @close="mappingOpen = false"
      @apply="onMappingApply"
    />
  </div>
</template>
