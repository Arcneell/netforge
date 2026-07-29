<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ImportErrorFilterBar from '@/components/import/ImportErrorFilterBar.vue'
import ImportErrorTable from '@/components/import/ImportErrorTable.vue'
import ImportReportHeader from '@/components/import/ImportReportHeader.vue'
import ImportReportStat from '@/components/import/ImportReportStat.vue'
import type { ImportEntity, ImportReport } from '@/api'
import { filterImportErrors } from '@/composables/importErrorFilter'
import { useImportEntityLabels } from '@/composables/useImportEntityLabels'

/** Outcome of a single-file run. */
const props = defineProps<{
  report: ImportReport
  /** Entity the file was imported as — named next to the summary. */
  entity: ImportEntity | null
  summary: string
}>()

const query = defineModel<string>('query', { required: true })

const { t } = useI18n()
const { entityLabel } = useImportEntityLabels()

const summaryPrefix = computed(() => (props.entity ? entityLabel(props.entity) : undefined))

const filteredRows = computed(() => filterImportErrors(props.report.error_rows, query.value))
</script>

<template>
  <section id="import-report" class="nf-card overflow-hidden" aria-live="polite">
    <ImportReportHeader
      :title="t('import.report.title')"
      :summary="summary"
      :summary-prefix="summaryPrefix"
      :applied="report.applied"
      :error-count="report.error_rows.length"
    >
      <template #stats>
        <ImportReportStat :value="report.parsed_rows" :label="t('import.report.parsedRows')" />
        <ImportReportStat
          :value="report.ok_rows"
          :label="t('import.report.okRows')"
          tone="success"
        />
        <ImportReportStat
          :value="report.error_rows.length"
          :label="t('import.report.errorRows')"
          tone="error"
        />
      </template>
    </ImportReportHeader>

    <template v-if="report.error_rows.length > 0">
      <ImportErrorFilterBar
        v-model:query="query"
        class="border-b border-border"
        :count="report.error_rows.length"
      />

      <ImportErrorTable v-if="filteredRows.length > 0" :rows="filteredRows" />
      <p v-else class="px-4 sm:px-5 py-4 text-base text-fg-muted">
        {{ t('import.report.errorsNoMatch') }}
      </p>
    </template>

    <p v-else class="px-4 sm:px-5 py-4 text-base text-fg-muted">
      {{ t('import.report.noErrors') }}
    </p>
  </section>
</template>
