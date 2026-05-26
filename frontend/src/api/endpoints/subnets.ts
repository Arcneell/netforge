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

/** One row in the dashboard capacity ranking. Cheap to render — no
 * per-address scan, just a few aggregates per subnet. */
export interface SubnetCapacityEntry {
  id: number
  cidr: string
  site_id: number
  vrf_id: number | null
  description: string | null
  usable: number
  used: number
  used_pct: number
}

export interface SubnetCapacityOverview {
  fullest: SubnetCapacityEntry[]
  full: SubnetCapacityEntry[]
  unused: SubnetCapacityEntry[]
  total_subnets: number
}

export type BulkIpAction = 'reserve' | 'release'
export type BulkIpStatus = 'reserved' | 'assigned' | 'dhcp'

export interface BulkIpRangePayload {
  action: BulkIpAction
  start: string
  end: string
  status?: BulkIpStatus
  overwrite?: boolean
  description?: string | null
}

export interface BulkIpResult {
  requested: number
  created: number
  updated: number
  deleted: number
  skipped: number
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
  /** Top-N capacity rankings for the dashboard heatmap. */
  capacityOverview(limit = 5): Promise<SubnetCapacityOverview> {
    return request<SubnetCapacityOverview>({
      method: 'GET',
      url: '/subnets/capacity-overview',
      params: { limit },
    })
  },
  /** Reserve or release every host in [start, end] in one call (admin). */
  bulkIpRange(id: number, payload: BulkIpRangePayload): Promise<BulkIpResult> {
    return request<BulkIpResult>({
      method: 'POST',
      url: `/subnets/${id}/bulk-ip`,
      data: payload,
    })
  },
  /** Fill-rate snapshot — cheap (two SELECTs), works on any prefix length. */
  utilization(id: number): Promise<SubnetUtilization> {
    return request<SubnetUtilization>({ method: 'GET', url: `/subnets/${id}/utilization` })
  },
}
