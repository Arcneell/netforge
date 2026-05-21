import { request } from '@/api/client'

export interface Vrf {
  id: number
  name: string
  rd: string | null
  description: string | null
  created_at: string
  updated_at: string
}

export interface VrfCreate {
  name: string
  rd?: string | null
  description?: string | null
}

export type VrfUpdate = Partial<VrfCreate>

export const vrfsApi = {
  list(): Promise<Vrf[]> {
    return request<Vrf[]>({ method: 'GET', url: '/vrfs' })
  },
  get(id: number): Promise<Vrf> {
    return request<Vrf>({ method: 'GET', url: `/vrfs/${id}` })
  },
  create(data: VrfCreate): Promise<Vrf> {
    return request<Vrf>({ method: 'POST', url: '/vrfs', data })
  },
  update(id: number, data: VrfUpdate): Promise<Vrf> {
    return request<Vrf>({ method: 'PUT', url: `/vrfs/${id}`, data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/vrfs/${id}` })
  },
}
