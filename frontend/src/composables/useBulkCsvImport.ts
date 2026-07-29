import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { importsApi, type BulkImportReport, type DetectReport } from '@/api'
import { useApiErrorMessage } from '@/composables/useApiErrorMessage'
import { useToast } from '@/composables/useToast'

/**
 * `(File, DetectReport | "pending" | "failed")` per slot. Detection runs
 * client-side as soon as a file lands so the UI can show a route before the
 * user even clicks "Run import".
 */
export interface BulkSlot {
  file: File
  detection: DetectReport | null
  detecting: boolean
  detectError: string | null
}

// Same limits as `csv_import.BULK_*` — duplicated client-side to give a
// fast preview before paying the round-trip.
export const BULK_MAX_FILES = 50
export const BULK_MAX_TOTAL_BYTES = 50 * 1024 * 1024
export const BULK_MAX_PER_FILE = 10 * 1024 * 1024

/**
 * Bulk import: drop every CSV (or a .zip) you have and let the backend route
 * each file to its entity. One transaction — any error rolls the batch back.
 */
export function useBulkCsvImport() {
  const { t } = useI18n()
  const { error: toastError } = useToast()
  const { describe } = useApiErrorMessage()

  const files = ref<BulkSlot[]>([])
  const dryRun = ref(true)
  const submitting = ref(false)
  const report = ref<BulkImportReport | null>(null)

  const totalBytes = computed(() => files.value.reduce((s, b) => s + b.file.size, 0))
  const overLimit = computed(() => totalBytes.value > BULK_MAX_TOTAL_BYTES)

  const canSubmit = computed(
    () =>
      files.value.length > 0 &&
      !submitting.value &&
      !overLimit.value &&
      files.value.every((b) => !b.detecting),
  )

  function acceptFile(f: File): boolean {
    const lower = f.name.toLowerCase()
    if (!lower.endsWith('.csv') && !lower.endsWith('.zip')) {
      toastError(t('import.errors.bulkNotCsvOrZip'))
      return false
    }
    if (f.size > BULK_MAX_PER_FILE) {
      toastError(t('import.errors.tooLarge'))
      return false
    }
    return true
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

  async function addFiles(incoming: FileList | File[]) {
    for (const f of incoming) {
      if (!acceptFile(f)) continue
      if (files.value.length >= BULK_MAX_FILES) {
        toastError(t('import.errors.tooManyFiles', { max: BULK_MAX_FILES }))
        break
      }
      const slot: BulkSlot = {
        file: f,
        detection: null,
        detecting: false,
        detectError: null,
      }
      files.value.push(slot)
      // ZIPs are not detected client-side — we only learn their contents after
      // the server unpacks them. Skip the per-file detection probe.
      if (f.name.toLowerCase().endsWith('.zip')) continue
      detectSlot(slot)
    }
  }

  function removeSlot(idx: number) {
    files.value.splice(idx, 1)
  }

  function clear() {
    files.value = []
    report.value = null
  }

  async function submit() {
    if (!canSubmit.value) return
    submitting.value = true
    try {
      const result = await importsApi.uploadBulk(
        files.value.map((b) => b.file),
        dryRun.value,
      )
      report.value = result
      queueMicrotask(() => {
        document
          .getElementById('bulk-report')
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

  return {
    files,
    dryRun,
    submitting,
    report,
    totalBytes,
    overLimit,
    canSubmit,
    addFiles,
    removeSlot,
    clear,
    submit,
    reportSummary,
  }
}
