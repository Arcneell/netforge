import { request } from '@/api/client'

// Hand-typed override — the generated schema still lists the old 4-type
// SearchResult; this widens it to the 8 entity types the backend now returns.
// Will be supplanted on the next `npm run gen:types`; the property names below
// match the generated shape so consumers don't have to change anything.
export type SearchResultType =
  | 'ip'
  | 'device'
  | 'switch'
  | 'port'
  | 'site'
  | 'room'
  | 'vlan'
  | 'subnet'

export interface SearchResult {
  type: SearchResultType
  id: number
  label: string
  context?: string | null
  parent_id?: number | null
}

export interface SearchResponse {
  results: SearchResult[]
}

export const searchApi = {
  search(q: string): Promise<SearchResponse> {
    return request<SearchResponse>({ method: 'GET', url: '/search', params: { q } })
  },
}
