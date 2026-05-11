import { request } from '@/api/client'
import type { Device, DeviceCreate, DeviceType, DeviceUpdate, Page, PageParams } from '@/api/types'

export interface DeviceFilters extends PageParams {
  type?: DeviceType
  room_id?: number
  q?: string
}

export const devicesApi = {
  list(filters: DeviceFilters = {}): Promise<Page<Device>> {
    return request<Page<Device>>({ method: 'GET', url: '/devices', params: filters })
  },
  get(id: number): Promise<Device> {
    return request<Device>({ method: 'GET', url: `/devices/${id}` })
  },
  create(data: DeviceCreate): Promise<Device> {
    return request<Device>({ method: 'POST', url: '/devices', data })
  },
  update(id: number, data: DeviceUpdate): Promise<Device> {
    return request<Device>({ method: 'PUT', url: `/devices/${id}`, data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/devices/${id}` })
  },
}
