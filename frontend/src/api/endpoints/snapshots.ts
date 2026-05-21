import { request } from '@/api/client'

export interface SnapshotEntityBucket {
  created: number
  updated: number
  deleted: number
  transient: number
}

export interface SnapshotSummary {
  total_audit_rows: number
  orphan_rows: number
  by_entity: Record<string, SnapshotEntityBucket>
}

export interface SnapshotChange {
  entity: string
  entity_id: number
  status: 'created' | 'updated' | 'deleted' | 'transient'
  actions_count: number
  first_action_at: string
  last_action_at: string
  fields_changed: string[]
}

export interface SnapshotCompareResponse {
  from_ts: string
  to_ts: string
  summary: SnapshotSummary
  changes: SnapshotChange[]
}

export interface SnapshotCompareParams {
  from: string
  to?: string
  entity?: string
}

export const snapshotsApi = {
  compare(params: SnapshotCompareParams): Promise<SnapshotCompareResponse> {
    return request<SnapshotCompareResponse>({
      method: 'GET',
      url: '/snapshots/compare',
      params,
    })
  },
}
