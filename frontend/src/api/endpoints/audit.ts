import { request } from '@/api/client'
import type { AuditAction, AuditLog, Page, PageParams } from '@/api/types'

export interface AuditFilters extends PageParams {
  entity?: string
  entity_id?: number
  /** Server-side filter on the action enum — replaces the client-side filter
   *  that used to discard rows after fetch, so `total` and pagination now
   *  reflect the filtered count instead of "all rows for this entity". */
  action?: AuditAction
  user_id?: number
  /** ISO 8601 datetime — backend filters created_at >= from */
  from?: string
  /** ISO 8601 datetime — backend filters created_at <= to */
  to?: string
}

export const auditApi = {
  list(filters: AuditFilters = {}): Promise<Page<AuditLog>> {
    return request<Page<AuditLog>>({ method: 'GET', url: '/audit', params: filters })
  },
  get(id: number): Promise<AuditLog> {
    return request<AuditLog>({ method: 'GET', url: `/audit/${id}` })
  },
}
