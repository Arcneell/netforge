import { request } from '@/api/client'
import type { Link, LinkCreate, Page, PageParams } from '@/api/types'

export interface LinkFilters extends PageParams {
  switch_id?: number
}

export const linksApi = {
  list(filters: LinkFilters = {}): Promise<Page<Link>> {
    return request<Page<Link>>({ method: 'GET', url: '/links', params: filters })
  },
  get(id: number): Promise<Link> {
    return request<Link>({ method: 'GET', url: `/links/${id}` })
  },
  /** No PUT — to change a link, delete and recreate. */
  create(data: LinkCreate): Promise<Link> {
    return request<Link>({ method: 'POST', url: '/links', data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/links/${id}` })
  },
}
