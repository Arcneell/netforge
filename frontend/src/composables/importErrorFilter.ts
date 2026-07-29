import type { ImportErrorRow } from '@/api'

/**
 * Error triage.
 *
 * A 400-row failure is unusable as a flat dump. One filter narrows every error
 * table on the page (single mode and each bulk file) to the lines that mention
 * a column, a value or a message.
 */
export function filterImportErrors(rows: ImportErrorRow[], query: string): ImportErrorRow[] {
  const q = query.trim().toLowerCase()
  if (!q) return rows
  return rows.filter(
    (e) =>
      String(e.line).includes(q) ||
      (e.column ?? '').toLowerCase().includes(q) ||
      (e.value ?? '').toLowerCase().includes(q) ||
      e.error.toLowerCase().includes(q),
  )
}
