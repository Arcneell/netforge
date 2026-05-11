import { request } from '@/api/client'
import type { Ip, IpCreate, IpStatus, IpUpdate, Page, PageParams } from '@/api/types'

export interface IpFilters extends PageParams {
  subnet_id?: number
  status?: IpStatus
  q?: string
}

export const ipsApi = {
  list(filters: IpFilters = {}): Promise<Page<Ip>> {
    return request<Page<Ip>>({ method: 'GET', url: '/ips', params: filters })
  },
  get(id: number): Promise<Ip> {
    return request<Ip>({ method: 'GET', url: `/ips/${id}` })
  },
  create(data: IpCreate): Promise<Ip> {
    return request<Ip>({ method: 'POST', url: '/ips', data })
  },
  update(id: number, data: IpUpdate): Promise<Ip> {
    return request<Ip>({ method: 'PUT', url: `/ips/${id}`, data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/ips/${id}` })
  },
}
