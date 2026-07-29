<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Badge from '@/components/ui/Badge.vue'
import ImportErrorFilterBar from '@/components/import/ImportErrorFilterBar.vue'
import ImportErrorTable from '@/components/import/ImportErrorTable.vue'
import ImportReportHeader from '@/components/import/ImportReportHeader.vue'
import ImportReportStat from '@/components/import/ImportReportStat.vue'
import type { BulkImportReport } from '@/api'
import { filterImportErrors } from '@/composables/importErrorFilter'
import { useImportEntityLabels } from '@/composables/useImportEntityLabels'
import { formatNumber } from '@/utils/formatters'

/** Outcome of a bulk run: one row per file, then the rejected lines grouped
 *  by the file they came from. */
const props = defineProps<{
  report: BulkImportReport
  summary: string
  errorCount: number
}>()

const query = defineModel<string>('query', { required: true })

const { t } = useI18n()
const { entityLabelOrFallback } = useImportEntityLabels()

/** Per-file rejections narrowed by the shared triage filter. */
const filteredFiles = computed(() =>
  props.report.files.map((file) => ({
    file,
    rows: filterImportErrors(file.error_rows, query.value),
  })),
)

// Bulk mode groups errors per file, so "no match" is only true when every
// file's filtered list came back empty.
const noErrorMatch = computed(() => {
  if (!query.value.trim() || props.errorCount === 0) return false
  return !filteredFiles.value.some((f) => f.rows.length > 0)
})
</script>

<template>
  <section id="bulk-report" class="nf-card overflow-hidden" aria-live="polite">
    <ImportReportHeader
      :title="t('import.bulk.report.title')"
      :summary="summary"
      :applied="report.applied"
      :error-count="errorCount"
    >
      <template #stats>
        <ImportReportStat :value="report.files.length" :label="t('import.bulk.report.files')" />
        <ImportReportStat
          :value="report.total_parsed_rows"
          :label="t('import.report.parsedRows')"
        />
        <ImportReportStat
          :value="report.total_ok_rows"
          :label="t('import.report.okRows')"
          tone="success"
        />
        <ImportReportStat :value="errorCount" :label="t('import.report.errorRows')" tone="error" />
      </template>
    </ImportReportHeader>

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
            v-for="(fileReport, i) in report.files"
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
    <ImportErrorFilterBar
      v-if="errorCount > 0"
      v-model:query="query"
      class="border-t border-border"
      :count="errorCount"
    />

    <!-- Per-file error details -->
    <template v-for="(entry, i) in filteredFiles" :key="`err-${i}`">
      <div
        v-if="entry.file.error_rows.length > 0 && entry.rows.length > 0"
        class="border-t border-border"
      >
        <p class="px-4 sm:px-5 py-2 text-xs text-fg-muted bg-muted/60">
          <span class="font-mono text-fg">{{ entry.file.filename }}</span>
          <span>· {{ formatNumber(entry.rows.length) }}</span>
        </p>
        <ImportErrorTable :rows="entry.rows" dense />
      </div>
    </template>

    <p v-if="noErrorMatch" class="border-t border-border px-4 sm:px-5 py-4 text-base text-fg-muted">
      {{ t('import.report.errorsNoMatch') }}
    </p>
  </section>
</template>
