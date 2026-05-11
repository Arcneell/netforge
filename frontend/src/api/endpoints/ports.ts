import { request } from '@/api/client'
import type { Page, PageParams, Port, PortUpdate } from '@/api/types'

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
