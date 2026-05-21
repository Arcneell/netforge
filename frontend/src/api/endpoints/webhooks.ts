import { request } from '@/api/client'

export interface Webhook {
  id: number
  name: string
  url: string
  events: string[]
  enabled: boolean
  total_deliveries: number
  total_failures: number
  last_delivery_at: string | null
  last_status_code: number | null
  last_error: string | null
  created_at: string
  updated_at: string
}

/** Returned by POST + rotate-secret — `secret` is shown once and never re-exposed. */
export interface WebhookCreated extends Webhook {
  secret: string
}

export interface WebhookCreate {
  name: string
  url: string
  events: string[]
  enabled?: boolean
}

export interface WebhookUpdate {
  name?: string
  url?: string
  events?: string[]
  enabled?: boolean
}

export interface WebhookDelivery {
  id: number
  webhook_id: number
  event: string
  status_code: number
  success: boolean
  error: string | null
  latency_ms: number
  created_at: string
}

export const webhooksApi = {
  list(): Promise<Webhook[]> {
    return request<Webhook[]>({ method: 'GET', url: '/webhooks' })
  },
  create(data: WebhookCreate): Promise<WebhookCreated> {
    return request<WebhookCreated>({ method: 'POST', url: '/webhooks', data })
  },
  get(id: number): Promise<Webhook> {
    return request<Webhook>({ method: 'GET', url: `/webhooks/${id}` })
  },
  update(id: number, data: WebhookUpdate): Promise<Webhook> {
    return request<Webhook>({ method: 'PATCH', url: `/webhooks/${id}`, data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/webhooks/${id}` })
  },
  rotateSecret(id: number): Promise<WebhookCreated> {
    return request<WebhookCreated>({
      method: 'POST',
      url: `/webhooks/${id}/rotate-secret`,
    })
  },
  test(id: number): Promise<WebhookDelivery> {
    return request<WebhookDelivery>({ method: 'POST', url: `/webhooks/${id}/test` })
  },
  listDeliveries(id: number, limit = 50): Promise<WebhookDelivery[]> {
    return request<WebhookDelivery[]>({
      method: 'GET',
      url: `/webhooks/${id}/deliveries`,
      params: { limit },
    })
  },
}
