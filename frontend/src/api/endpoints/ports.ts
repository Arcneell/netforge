import { request } from '@/api/client'
import type { Page, PageParams, Port, PortUpdate, Vlan } from '@/api/types'

export const portsApi = {
  /** Nested route — paginated; backend default page_size=50, max 200. */
  listForSwitch(switchId: number, params: PageParams = {}): Promise<Page<Port>> {
    return request<Page<Port>>({
      method: 'GET',
      url: `/switches/${switchId}/ports`,
      params,
    })
  },
  get(id: number): Promise<Port> {
    return request<Port>({ method: 'GET', url: `/ports/${id}` })
  },
  update(id: number, data: PortUpdate): Promise<Port> {
    return request<Port>({ method: 'PUT', url: `/ports/${id}`, data })
  },
  /** Batch read of the trunk's tagged VLAN set. PortEditor calls this on open
   * so the list reflects the actual server state instead of resetting empty. */
  listTaggedVlans(portId: number): Promise<Vlan[]> {
    return request<Vlan[]>({ method: 'GET', url: `/ports/${portId}/vlans` })
  },
  addTaggedVlan(portId: number, vlanId: number): Promise<void> {
    return request<void>({
      method: 'POST',
      url: `/ports/${portId}/vlans`,
      data: { vlan_id: vlanId },
    })
  },
  removeTaggedVlan(portId: number, vlanId: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/ports/${portId}/vlans/${vlanId}` })
  },
}
