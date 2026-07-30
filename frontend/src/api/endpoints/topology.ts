import { request } from '@/api/client'
import type { TopologyResponse } from '@/api/types'

export interface TopologyQuery {
  /** Restrict to switches and devices in this site. */
  siteId?: number | null
  /** Restrict to a single room. */
  roomId?: number | null
  /**
   * Keep only switches carrying this VLAN (native or tagged) on at least one
   * port. Every link between those switches is still returned.
   */
  vlanId?: number | null
  /**
   * Include non-switch devices as leaf nodes, with an `attachment` edge per
   * port they're plugged into. Off gives a switch-only backbone view.
   */
  includeDevices?: boolean
}

export const topologyApi = {
  /**
   * Returns the graph in Cytoscape element shape: `{ nodes, edges, stats }`.
   * Nodes carry a `parent` id so sites and rooms render as compound group
   * boxes without the client reconstructing the hierarchy.
   */
  get(query: TopologyQuery = {}): Promise<TopologyResponse> {
    const params = new URLSearchParams()
    if (query.siteId) params.set('site_id', String(query.siteId))
    if (query.roomId) params.set('room_id', String(query.roomId))
    if (query.vlanId) params.set('vlan_id', String(query.vlanId))
    // Only sent when explicitly off — the backend default is on, so omitting
    // it keeps the query string short for the common case.
    if (query.includeDevices === false) params.set('include_devices', 'false')
    const qs = params.toString()
    return request<TopologyResponse>({
      method: 'GET',
      url: qs ? `/topology?${qs}` : '/topology',
    })
  },
}
