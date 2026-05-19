import { request } from '@/api/client'
import type { Link } from '@/api/types'

export interface AIStatus {
  enabled: boolean
  provider: string
  model: string
  /** Per-feature toggles. `enabled` is the master switch; these sub-flags
   *  reflect `AI_DRAFTS_ENABLED` / `AI_SCHEDULER_ENABLED` envs ANDed with
   *  the master. UI hides the matching sections when false. */
  drafts_enabled: boolean
  scheduler_enabled: boolean
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
  /** ISO-8601 timestamp of the run that produced these insights, or null when
   *  no advisor run has ever succeeded. Used by the UI to render a "generated
   *  X days ago" hint. */
  run_created_at: string | null
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

export interface QueryEntityRef {
  type: 'site' | 'room' | 'switch' | 'port' | 'vlan' | 'subnet' | 'device' | string
  id: number
  name: string | null
}

export interface QueryAnswer {
  answer: string
  referenced_entities: QueryEntityRef[]
  provider: string
  model: string
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
}

export interface QueryHistoryTurn {
  role: 'user' | 'assistant'
  text: string
}

// --- AI Usage dashboard ----------------------------------------------------

export interface UsageTotal {
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
  success: number
  failure: number
  avg_latency_ms: number
}

export interface UsageBucket {
  key: string
  totals: UsageTotal
}

export interface UsageReport {
  window_days: number
  started_at: string
  total: UsageTotal
  by_day: UsageBucket[]
  by_kind: UsageBucket[]
  by_provider: UsageBucket[]
}

export interface IntegrityIssue {
  severity: InsightSeverity
  category: InsightCategory
  title: string
  description: string
  recommendation: string
  affected_entities: InsightEntityRef[]
}

export interface IntegrityReport {
  issues: IntegrityIssue[]
}

// --- CSV mapping assistant -------------------------------------------------

export interface CsvMappingRequest {
  entity: string
  csv_columns: string[]
  /** Each row is an array aligned with `csv_columns`. */
  sample_rows: string[][]
}

export interface CsvColumnMapping {
  csv_column: string
  suggested_field: string | null
  confidence: number
  notes: string
}

export interface CsvMappingResponse {
  entity: string
  columns: CsvColumnMapping[]
  missing_required_fields: string[]
  provider: string
  model: string
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
}

// --- Scheduled AI runs -----------------------------------------------------

export type AIScheduleKind = 'advisor' | 'suggest_links'

export interface AISchedule {
  id: number
  kind: AIScheduleKind
  enabled: boolean
  interval_minutes: number
  webhook_url: string | null
  webhook_severity_threshold: InsightSeverity
  last_run_at: string | null
  last_run_id: number | null
}

export interface AIScheduleUpsert {
  enabled: boolean
  interval_minutes: number
  webhook_url: string | null
  webhook_severity_threshold: InsightSeverity
}

// --- NL-to-action drafts ---------------------------------------------------

export type ActionDraftStatus = 'pending' | 'applied' | 'rejected' | 'failed'

export interface ActionDraft {
  id: number
  user_id: number | null
  prompt: string
  intent: string
  payload: Record<string, unknown>
  status: ActionDraftStatus
  error_message: string | null
  applied_resource: string | null
  applied_by_user_id: number | null
  applied_at: string | null
  created_at: string
}

// LLM calls routinely take 20–60 s on a real inventory snapshot; the default
// axios 20 s timeout was aborting valid responses mid-flight ("Impossible de
// joindre le serveur"). Bump the AI-specific endpoints to 120 s — generous
// enough for the slowest provider/advisor combo we've seen, still short
// enough to fail fast when a key is invalid or the network is down.
const AI_TIMEOUT_MS = 120_000

export const aiApi = {
  status(): Promise<AIStatus> {
    return request<AIStatus>({ method: 'GET', url: '/ai/status' })
  },
  test(): Promise<AITestResult> {
    return request<AITestResult>({ method: 'POST', url: '/ai/test', timeout: AI_TIMEOUT_MS })
  },
  scanLinks(): Promise<ScanReport> {
    return request<ScanReport>({
      method: 'POST',
      url: '/ai/suggestions/links/scan',
      timeout: AI_TIMEOUT_MS,
    })
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
    return request<AdvisorReport>({
      method: 'POST',
      url: '/ai/insights/refresh',
      timeout: AI_TIMEOUT_MS,
    })
  },
  /**
   * One-shot NL question. `history` is replayed by the server on each call
   * (the server is stateless); pass an empty array to start a fresh chat.
   * The server caps history at 10 turns — the client should already trim
   * before sending to keep tokens down.
   */
  ask(question: string, history: QueryHistoryTurn[] = []): Promise<QueryAnswer> {
    return request<QueryAnswer>({
      method: 'POST',
      url: '/ai/query',
      data: { question, history },
      timeout: AI_TIMEOUT_MS,
    })
  },
  /** Aggregate AI usage over `days` days (1–365, default 30 server-side). */
  usage(days?: number): Promise<UsageReport> {
    return request<UsageReport>({
      method: 'GET',
      url: '/ai/usage',
      params: days !== undefined ? { days } : undefined,
    })
  },
  /** Deterministic integrity checks (no LLM call). Always available, even
   *  when AI is otherwise disabled. */
  integrityChecks(): Promise<IntegrityReport> {
    return request<IntegrityReport>({ method: 'GET', url: '/ai/integrity-checks' })
  },
  suggestCsvMapping(req: CsvMappingRequest): Promise<CsvMappingResponse> {
    return request<CsvMappingResponse>({
      method: 'POST',
      url: '/ai/csv/suggest-mapping',
      data: req,
      timeout: AI_TIMEOUT_MS,
    })
  },
  listSchedules(): Promise<AISchedule[]> {
    return request<AISchedule[]>({ method: 'GET', url: '/ai/schedules' })
  },
  upsertSchedule(kind: AIScheduleKind, body: AIScheduleUpsert): Promise<AISchedule> {
    return request<AISchedule>({
      method: 'PUT',
      url: `/ai/schedules/${kind}`,
      data: body,
    })
  },
  createDraft(prompt: string): Promise<ActionDraft> {
    return request<ActionDraft>({
      method: 'POST',
      url: '/ai/drafts',
      data: { prompt },
      timeout: AI_TIMEOUT_MS,
    })
  },
  listDrafts(): Promise<ActionDraft[]> {
    return request<ActionDraft[]>({ method: 'GET', url: '/ai/drafts' })
  },
  applyDraft(id: number): Promise<ActionDraft> {
    return request<ActionDraft>({ method: 'POST', url: `/ai/drafts/${id}/apply` })
  },
  rejectDraft(id: number): Promise<ActionDraft> {
    return request<ActionDraft>({ method: 'POST', url: `/ai/drafts/${id}/reject` })
  },
}
