import { api } from '@/api/client'
import type { ImportReport } from '@/api/types'

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

export const importsApi = {
  /**
   * Upload a CSV file. With `dry_run=true` the backend parses and validates
   * but always rolls back — same shape of report either way.
   *
   * We bypass the standard request() helper because we need a multipart body
   * (axios builds the boundary from FormData automatically).
   */
  async upload(entity: ImportEntity, file: File, dryRun: boolean): Promise<ImportReport> {
    const form = new FormData()
    form.append('file', file)
    form.append('dry_run', dryRun ? 'true' : 'false')
    const res = await api.post<ImportReport>(`/imports/${entity}`, form)
    return res.data
  },
}
