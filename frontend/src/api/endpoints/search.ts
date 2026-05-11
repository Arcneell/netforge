import { request } from '@/api/client'
import type { SearchResponse } from '@/api/types'

export const searchApi = {
  search(q: string): Promise<SearchResponse> {
    return request<SearchResponse>({ method: 'GET', url: '/search', params: { q } })
  },
}
