import { request } from '@/api/client'
import type { Page, PageParams, Vlan, VlanCreate, VlanUpdate } from '@/api/types'

export const vlansApi = {
  list(params: PageParams = {}): Promise<Page<Vlan>> {
    return request<Page<Vlan>>({ method: 'GET', url: '/vlans', params })
  },
  get(id: number): Promise<Vlan> {
    return request<Vlan>({ method: 'GET', url: `/vlans/${id}` })
  },
  create(data: VlanCreate): Promise<Vlan> {
    return request<Vlan>({ method: 'POST', url: '/vlans', data })
  },
  update(id: number, data: VlanUpdate): Promise<Vlan> {
    return request<Vlan>({ method: 'PUT', url: `/vlans/${id}`, data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/vlans/${id}` })
  },
}
