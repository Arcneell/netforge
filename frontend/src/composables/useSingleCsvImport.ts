import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { importsApi, type ImportEntity, type ImportReport } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

/**
 * Single-file import (legacy flow): the operator picks one entity and one
 * CSV. Kept for power users who want to target a specific entity with a
 * fixed file; bulk mode is the default everywhere else.
 */
export function useSingleCsvImport() {
  const { t } = useI18n()
  const { error: toastError } = useToast()
  const { describe } = useApiErrorMessage()

  const entity = ref<ImportEntity>('sites')
  const file = ref<File | null>(null)
  const dryRun = ref(true)
  const submitting = ref(false)
  const report = ref<ImportReport | null>(null)
  const lastEntity = ref<ImportEntity | null>(null)

  // AI-assisted column mapping. When the assistant emits `apply`, we stash the
  // mapping here. The next `submit()` forwards it to the backend as
  // `column_map` (server-side header rewrite) and then clears the slot so a
  // subsequent import doesn't silently keep using stale field translations.
  const pendingMapping = ref<Record<string, string | null> | null>(null)
  const pendingMappingEntity = ref<ImportEntity | null>(null)

  function applyMapping(mapping: Record<string, string | null>, mappedEntity: ImportEntity) {
    pendingMapping.value = mapping
    pendingMappingEntity.value = mappedEntity
    // Auto-switch the single-import dropdown to the entity the mapping was
    // built for — avoids the surprise of "I mapped for switches but the
    // upload tab is still on sites".
    entity.value = mappedEntity
  }

  async function submit() {
    if (!file.value || submitting.value) return
    submitting.value = true
    try {
      // Use the pending mapping iff it was prepared for THIS entity — keeps
      // a stale mapping from accidentally rewriting a different file's
      // headers when the user switches entities between mapping and upload.
      const mapping =
        pendingMappingEntity.value === entity.value
          ? (pendingMapping.value ?? undefined)
          : undefined
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

  const reportSummary = computed(() => {
    const r = report.value
    if (!r) return ''
    if (r.error_rows.length > 0)
      return t('import.report.partial', { ok: r.ok_rows, total: r.parsed_rows })
    if (r.applied) return t('import.report.successAll', { count: r.ok_rows })
    return t('import.report.successDryRun', { count: r.ok_rows })
  })

  return {
    entity,
    file,
    dryRun,
    submitting,
    report,
    lastEntity,
    pendingMapping,
    pendingMappingEntity,
    applyMapping,
    submit,
    reportSummary,
  }
}
