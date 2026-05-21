import { request } from '@/api/client'

export interface Cable {
  id: number
  label: string | null
  link_id: number | null
  length_m: number | null
  color: string | null
  vendor: string | null
  part_number: string | null
  serial: string | null
  installed_on: string | null
  last_tested_on: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface CableCreate {
  label?: string | null
  link_id?: number | null
  length_m?: number | null
  color?: string | null
  vendor?: string | null
  part_number?: string | null
  serial?: string | null
  installed_on?: string | null
  last_tested_on?: string | null
  notes?: string | null
}

export type CableUpdate = CableCreate

export const cablesApi = {
  list(in_stock = false): Promise<Cable[]> {
    return request<Cable[]>({ method: 'GET', url: '/cables', params: { in_stock } })
  },
  get(id: number): Promise<Cable> {
    return request<Cable>({ method: 'GET', url: `/cables/${id}` })
  },
  create(data: CableCreate): Promise<Cable> {
    return request<Cable>({ method: 'POST', url: '/cables', data })
  },
  update(id: number, data: CableUpdate): Promise<Cable> {
    return request<Cable>({ method: 'PUT', url: `/cables/${id}`, data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/cables/${id}` })
  },
  /** Read the cable attached to a link. Throws 404 if there isn't one yet. */
  forLink(linkId: number): Promise<Cable> {
    return request<Cable>({ method: 'GET', url: `/links/${linkId}/cable` })
  },
}
