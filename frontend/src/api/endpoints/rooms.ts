import { request } from '@/api/client'
import type { Page, PageParams, Room, RoomCreate, RoomUpdate } from '@/api/types'

export interface RoomFilters extends PageParams {
  site_id?: number
}

export const roomsApi = {
  list(filters: RoomFilters = {}): Promise<Page<Room>> {
    return request<Page<Room>>({ method: 'GET', url: '/rooms', params: filters })
  },
  get(id: number): Promise<Room> {
    return request<Room>({ method: 'GET', url: `/rooms/${id}` })
  },
  create(data: RoomCreate): Promise<Room> {
    return request<Room>({ method: 'POST', url: '/rooms', data })
  },
  update(id: number, data: RoomUpdate): Promise<Room> {
    return request<Room>({ method: 'PUT', url: `/rooms/${id}`, data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/rooms/${id}` })
  },
}
