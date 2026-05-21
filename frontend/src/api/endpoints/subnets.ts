import { request } from '@/api/client'
import type {
  NextFreeIp,
  Page,
  PageParams,
  Subnet,
  SubnetCreate,
  SubnetIpsResponse,
  SubnetUpdate,
  SubnetUtilization,
} from '@/api/types'

export interface SubnetFilters extends PageParams {
  site_id?: number
  vlan_id?: number
}

export const subnetsApi = {
  list(filters: SubnetFilters = {}): Promise<Page<Subnet>> {
    return request<Page<Subnet>>({ method: 'GET', url: '/subnets', params: filters })
  },
  get(id: number): Promise<Subnet> {
    return request<Subnet>({ method: 'GET', url: `/subnets/${id}` })
  },
  create(data: SubnetCreate): Promise<Subnet> {
    return request<Subnet>({ method: 'POST', url: '/subnets', data })
  },
  update(id: number, data: SubnetUpdate): Promise<Subnet> {
    return request<Subnet>({ method: 'PUT', url: `/subnets/${id}`, data })
  },
  delete(id: number): Promise<void> {
    return request<void>({ method: 'DELETE', url: `/subnets/${id}` })
  },
  /** Returns the subnet plus every IP (registered or synthetic-free). */
  ips(id: number): Promise<SubnetIpsResponse> {
    return request<SubnetIpsResponse>({ method: 'GET', url: `/subnets/${id}/ips` })
  },
  /** Pure read — does not reserve, just suggests. */
  nextFree(id: number): Promise<NextFreeIp> {
    return request<NextFreeIp>({ method: 'POST', url: `/subnets/${id}/next-free` })
  },
  /** Fill-rate snapshot — cheap (two SELECTs), works on any prefix length. */
  utilization(id: number): Promise<SubnetUtilization> {
    return request<SubnetUtilization>({ method: 'GET', url: `/subnets/${id}/utilization` })
  },
}
