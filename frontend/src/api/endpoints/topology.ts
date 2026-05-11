import { request } from '@/api/client'
import type { TopologyResponse } from '@/api/types'

export const topologyApi = {
  /** Returns the full graph in Cytoscape-friendly shape: { nodes, edges }. */
  get(): Promise<TopologyResponse> {
    return request<TopologyResponse>({ method: 'GET', url: '/topology' })
  },
}
