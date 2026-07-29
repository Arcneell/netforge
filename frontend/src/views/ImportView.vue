<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Download, UploadCloud, Wand2 } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import Segmented, { type SegmentedOption } from '@/components/ui/Segmented.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import EmptyState from '@/components/EmptyState.vue'
import CsvMappingAssistant from '@/components/CsvMappingAssistant.vue'
import BulkImportPanel from '@/components/import/BulkImportPanel.vue'
import BulkImportReportSection from '@/components/import/BulkImportReportSection.vue'
import ImportStepsRail from '@/components/import/ImportStepsRail.vue'
import SingleImportPanel from '@/components/import/SingleImportPanel.vue'
import SingleImportReportSection from '@/components/import/SingleImportReportSection.vue'
import type { BulkImportReport, ImportReport } from '@/api'
import { useBulkCsvImport } from '@/composables/useBulkCsvImport'
import { useSingleCsvImport } from '@/composables/useSingleCsvImport'

const { t } = useI18n()

// Tab state: "bulk" is the new default because most users just want to drop
// every CSV they have and let the backend route them. "single" stays for
// power users who want to target a specific entity with a fixed file.
type Mode = 'bulk' | 'single'
const mode = ref<Mode>('bulk')

const {
  entity,
  file: singleFile,
  dryRun: singleDryRun,
  submitting: singleSubmitting,
  report: singleReport,
  lastEntity,
  pendingMapping,
  pendingMappingEntity,
  applyMapping,
  submit: submitSingle,
  reportSummary: singleReportSummary,
} = useSingleCsvImport()

const {
  files: bulkFiles,
  dryRun: bulkDryRun,
  submitting: bulkSubmitting,
  report: bulkReport,
  totalBytes: bulkTotalBytes,
  overLimit: bulkOverLimit,
  canSubmit: canSubmitBulk,
  addFiles: addBulkFiles,
  removeSlot: removeBulkSlot,
  clear: clearBulk,
  submit: submitBulk,
  reportSummary: bulkReportSummary,
} = useBulkCsvImport()

// AI-assisted column mapping modal — opened by the "Need help mapping?"
// button. Always available; the LLM call is admin-only and rate-limited.
const mappingOpen = ref(false)

function downloadAll() {
  // Browser handles the streamed ZIP download. The endpoint accepts any
  // authenticated user — backend is the source of truth for permissions.
  window.open('/api/exports/all', '_blank', 'noopener')
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
  mode.value === 'bulk' ? bulkReport.value : singleReport.value,
)

const hasPickedFiles = computed(() =>
  mode.value === 'bulk' ? bulkFiles.value.length > 0 : !!singleFile.value,
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

// One filter narrows every error table on the page (single mode and each
// bulk file); it lives here so it survives a mode switch.
const errorQuery = ref('')
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
    <ImportStepsRail :current-step="currentStep" :applied="activeApplied" />

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
    <BulkImportPanel
      v-if="mode === 'bulk'"
      v-model:dry-run="bulkDryRun"
      :files="bulkFiles"
      :submitting="bulkSubmitting"
      :total-bytes="bulkTotalBytes"
      :over-limit="bulkOverLimit"
      :can-submit="canSubmitBulk"
      @add-files="addBulkFiles"
      @remove="removeBulkSlot"
      @clear="clearBulk"
      @submit="submitBulk"
    />

    <!-- =================== SINGLE MODE (legacy) =================== -->
    <SingleImportPanel
      v-else
      v-model:entity="entity"
      v-model:file="singleFile"
      v-model:dry-run="singleDryRun"
      :submitting="singleSubmitting"
      @submit="submitSingle"
    />

    <!-- =================== BULK REPORT =================== -->
    <BulkImportReportSection
      v-if="bulkReport && mode === 'bulk'"
      v-model:query="errorQuery"
      :report="bulkReport"
      :summary="bulkReportSummary"
      :error-count="activeErrorCount"
    />

    <!-- =================== SINGLE-MODE REPORT =================== -->
    <SingleImportReportSection
      v-else-if="singleReport && mode === 'single'"
      v-model:query="errorQuery"
      :report="singleReport"
      :entity="lastEntity"
      :summary="singleReportSummary"
    />

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
      @apply="applyMapping"
    />
  </div>
</template>
