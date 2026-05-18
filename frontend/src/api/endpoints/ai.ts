import { request } from '@/api/client'
import type { Link } from '@/api/types'

export interface AIStatus {
  enabled: boolean
  provider: string
  model: string
}

export type LinkSuggestionStatus = 'pending' | 'accepted' | 'rejected' | 'superseded'

export interface LinkSuggestion {
  id: number
  port_a_id: number
  port_b_id: number
  /** Backend-resolved labels (port label / switch name). Null when the
   *  underlying port was deleted between scan and read. */
  port_a_label: string | null
  port_b_label: string | null
  switch_a_name: string | null
  switch_b_name: string | null
  link_type: 'copper' | 'fiber' | 'dac' | 'virtual' | string
  confidence: number
  reasoning: string
  status: LinkSuggestionStatus
  accepted_link_id: number | null
  resolved_by_user_id: number | null
  resolved_at: string | null
  created_at: string
}

export interface ScanReport {
  run_id: number
  provider: string
  model: string
  raw_count: number
  persisted_count: number
  skipped_count: number
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
}

export const aiApi = {
  status(): Promise<AIStatus> {
    return request<AIStatus>({ method: 'GET', url: '/ai/status' })
  },
  scanLinks(): Promise<ScanReport> {
    return request<ScanReport>({ method: 'POST', url: '/ai/suggestions/links/scan' })
  },
  listSuggestions(): Promise<LinkSuggestion[]> {
    return request<LinkSuggestion[]>({ method: 'GET', url: '/ai/suggestions/links' })
  },
  acceptSuggestion(id: number): Promise<Link> {
    return request<Link>({ method: 'POST', url: `/ai/suggestions/${id}/accept` })
  },
  rejectSuggestion(id: number): Promise<LinkSuggestion> {
    return request<LinkSuggestion>({ method: 'POST', url: `/ai/suggestions/${id}/reject` })
  },
}
