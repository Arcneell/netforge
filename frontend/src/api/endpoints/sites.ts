import { request } from '@/api/client'
import type { Page, PageParams, Site, SiteCreate, SiteUpdate } from '@/api/types'

export const sitesApi = {
  list(params: PageParams = {}): Promise<Page<Site>> {
    return request<Page<Site>>({ method: 'GET', url: '/sites', params })
  },
  get(id: number): Promise<Site> {
    return request<Site>({ method: 'GET', url: `/sites/${id}` })
  },
  create(data: SiteCreate): Promise<Site> {
    return request<Site>({ method: 'POST', url: '/sites', data })
  },
  update(id: number, data: SiteUpdate): Promise<Site> {
    return request<Site>({ method: 'PUT', url: `/sites/${id}`, data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/sites/${id}` })
  },
}
