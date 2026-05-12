import { request } from '@/api/client'
import type { Link, LinkCreate, LinkType, Page, PageParams } from '@/api/types'

export interface LinkFilters extends PageParams {
  switch_id?: number
}

// Hand-typed mirrors of the two new endpoint payloads. Will be supplanted by
// generated equivalents on the next `npm run gen:types`.
export interface LinkCreateByName {
  switch_a: string
  port_a: number
  switch_b: string
  port_b: number
  link_type: LinkType
  speed_mbps?: number | null
  description?: string | null
}

export interface LinkUpdate {
  link_type?: LinkType | null
  speed_mbps?: number | null
  description?: string | null
}

export const linksApi = {
  list(filters: LinkFilters = {}): Promise<Page<Link>> {
    return request<Page<Link>>({ method: 'GET', url: '/links', params: filters })
  },
  get(id: number): Promise<Link> {
    return request<Link>({ method: 'GET', url: `/links/${id}` })
  },
  create(data: LinkCreate): Promise<Link> {
    return request<Link>({ method: 'POST', url: '/links', data })
  },
  /**
   * Create a link by (switch name, port number) — what the topology editor
   * has in hand. The backend resolves both endpoints to port ids.
   */
  createByName(data: LinkCreateByName): Promise<Link> {
    return request<Link>({ method: 'POST', url: '/links/by-name', data })
  },
  /**
   * Patch metadata only (type, speed, description). Endpoints are immutable
   * at this route — to change connected ports, delete and recreate.
   */
  update(id: number, data: LinkUpdate): Promise<Link> {
    return request<Link>({ method: 'PUT', url: `/links/${id}`, data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/links/${id}` })
  },
}
