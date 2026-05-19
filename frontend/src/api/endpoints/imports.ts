import { api } from '@/api/client'
import type { ImportErrorRow, ImportReport } from '@/api/types'

/**
 * Entities supported by both the import and export CSV endpoints. Keep this
 * in sync with `backend/app/services/csv_export.py::ENTITIES` and the keys of
 * `backend/app/services/csv_import.py::SPECS`.
 */
export const IMPORT_ENTITIES = [
  'sites',
  'rooms',
  'vlans',
  'subnets',
  'devices',
  'switches',
  'ports',
  'ips',
  'links',
] as const
export type ImportEntity = (typeof IMPORT_ENTITIES)[number]

// Hand-typed mirrors of the new `/detect` and `/bulk` schemas. Will be
// supplanted by generated equivalents on the next `npm run gen:types`; if
// that pass introduces a name conflict, switch to `import type { DetectReport
// } from '@/api/types'` and delete the local declarations.
export interface DetectReport {
  entity: ImportEntity | null
  confidence: number
  headers: string[]
  matched_required: string[]
  missing_required: string[]
  unknown_headers: string[]
  candidates: Record<string, number>
}

export interface BulkImportFileReport {
  filename: string
  detected_entity: ImportEntity | null
  parsed_rows: number
  ok_rows: number
  error_rows: ImportErrorRow[]
}

export interface BulkImportReport {
  files: BulkImportFileReport[]
  total_parsed_rows: number
  total_ok_rows: number
  applied: boolean
}

export const importsApi = {
  /**
   * Upload a CSV file. With `dry_run=true` the backend parses and validates
   * but always rolls back — same shape of report either way.
   *
   * We bypass the standard request() helper because we need a multipart body
   * (axios builds the boundary from FormData automatically).
   */
  /**
   * Upload a CSV file. With `dry_run=true` the backend parses and validates
   * but always rolls back — same shape of report either way.
   *
   * `columnMap` is the optional AI-mapping output (`{csv_column: canonical |
   * null}`): when present, the backend rewrites the CSV header row before
   * parsing. Use it to feed in foreign headers without the operator having
   * to manually rename them.
   */
  async upload(
    entity: ImportEntity,
    file: File,
    dryRun: boolean,
    columnMap?: Record<string, string | null>,
  ): Promise<ImportReport> {
    const form = new FormData()
    form.append('file', file)
    form.append('dry_run', dryRun ? 'true' : 'false')
    if (columnMap && Object.keys(columnMap).length > 0) {
      form.append('column_map', JSON.stringify(columnMap))
    }
    const res = await api.post<ImportReport>(`/imports/${entity}`, form)
    return res.data
  },

  /**
   * Ask the backend to guess which entity a CSV belongs to by inspecting its
   * header row. Lets the UI auto-route a file without prompting the user.
   */
  async detect(file: File): Promise<DetectReport> {
    const form = new FormData()
    form.append('file', file)
    const res = await api.post<DetectReport>('/imports/detect', form)
    return res.data
  },

  /**
   * Bulk-import many CSVs (or a single .zip) in a single transaction. Each
   * file is routed to the correct entity by header detection; on any error
   * the whole batch is rolled back.
   */
  async uploadBulk(files: File[], dryRun: boolean): Promise<BulkImportReport> {
    const form = new FormData()
    for (const f of files) form.append('files', f)
    form.append('dry_run', dryRun ? 'true' : 'false')
    const res = await api.post<BulkImportReport>('/imports/bulk', form)
    return res.data
  },
}
