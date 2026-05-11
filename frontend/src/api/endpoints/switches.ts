import { request } from '@/api/client'
import type { Page, PageParams, Switch, SwitchCreate, SwitchUpdate } from '@/api/types'

export interface SwitchFilters extends PageParams {
  room_id?: number
}

export const switchesApi = {
  list(filters: SwitchFilters = {}): Promise<Page<Switch>> {
    return request<Page<Switch>>({ method: 'GET', url: '/switches', params: filters })
  },
  get(id: number): Promise<Switch> {
    return request<Switch>({ method: 'GET', url: `/switches/${id}` })
  },
  /** Side effect: creates `port_count` ports numbered 1..N. */
  create(data: SwitchCreate): Promise<Switch> {
    return request<Switch>({ method: 'POST', url: '/switches', data })
  },
  /** `port_count` is intentionally immutable on the backend (avoids port-id churn). */
  update(id: number, data: SwitchUpdate): Promise<Switch> {
    return request<Switch>({ method: 'PUT', url: `/switches/${id}`, data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/switches/${id}` })
  },
}
