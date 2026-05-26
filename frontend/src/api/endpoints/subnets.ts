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
  /** 0 = global scope only; positive = that VRF only. Omit for all. */
  vrf_id?: number
  /** Free-text search over CIDR + description. Trigram-indexed in DB. */
  q?: string
}

export interface SubnetTreeNode {
  id: number
  cidr: string
  site_id: number
  vrf_id: number | null
  vlan_id: number | null
  parent_subnet_id: number | null
  description: string | null
  gateway: string | null
  /** Total host-usable addresses in the CIDR (excludes network/broadcast on /≤30). */
  usable: number
  /** Number of `Ip` rows actually recorded in this subnet. */
  used: number
  /** True for virtual supernets synthesised by the backend's auto-group:
   * no DB row, can't be opened in the editor, and `id` is negative. */
  synthetic?: boolean
  children: SubnetTreeNode[]
}

export const subnetsApi = {
  list(filters: SubnetFilters = {}): Promise<Page<Subnet>> {
    return request<Page<Subnet>>({ method: 'GET', url: '/subnets', params: filters })
  },
  /** Hierarchical view. `vrf_id` omitted or 0 = global scope. */
  tree(vrf_id?: number): Promise<SubnetTreeNode[]> {
    return request<SubnetTreeNode[]>({
      method: 'GET',
      url: '/subnets/tree',
      params: vrf_id !== undefined ? { vrf_id } : undefined,
    })
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
