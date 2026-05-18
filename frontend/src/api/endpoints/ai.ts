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

export interface AITestResult {
  ok: boolean
  provider: string
  model: string
  latency_ms: number
  error: string | null
}

export type InsightSeverity = 'info' | 'warning' | 'critical'
export type InsightCategory =
  | 'spof'
  | 'capacity'
  | 'security'
  | 'segmentation'
  | 'naming'
  | 'redundancy'
  | 'other'

export interface InsightEntityRef {
  type: 'site' | 'room' | 'switch' | 'port' | 'vlan' | 'subnet' | 'device' | string
  id: number
  name: string | null
}

export interface Insight {
  id: number
  run_id: number
  severity: InsightSeverity
  category: InsightCategory
  title: string
  description: string
  recommendation: string
  affected_entities: InsightEntityRef[] | null
  created_at: string
}

export interface InsightsResponse {
  run_id: number | null
  insights: Insight[]
}

export interface AdvisorReport {
  run_id: number
  provider: string
  model: string
  raw_count: number
  persisted_count: number
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
}

export const aiApi = {
  status(): Promise<AIStatus> {
    return request<AIStatus>({ method: 'GET', url: '/ai/status' })
  },
  test(): Promise<AITestResult> {
    return request<AITestResult>({ method: 'POST', url: '/ai/test' })
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
  getInsights(): Promise<InsightsResponse> {
    return request<InsightsResponse>({ method: 'GET', url: '/ai/insights' })
  },
  refreshInsights(): Promise<AdvisorReport> {
    return request<AdvisorReport>({ method: 'POST', url: '/ai/insights/refresh' })
  },
}
