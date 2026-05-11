import { request } from '@/api/client'

export interface HealthResponse {
  status: 'ok' | 'degraded'
  database: 'up' | 'down'
  version?: string
}

export const healthApi = {
  check(): Promise<HealthResponse> {
    return request<HealthResponse>({ method: 'GET', url: '/health' })
  },
}
