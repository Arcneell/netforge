/**
 * Re-export of the generated OpenAPI schema under ergonomic, hand-curated names.
 *
 * The generator (`openapi-typescript`) produces awkward nested paths like
 * `components["schemas"]["SiteRead"]`. We alias them here so the rest of the
 * codebase can `import type { Site } from '@/api/types'` instead.
 *
 * Whenever the backend changes, run `npm run gen:types` and update this file
 * if any name moved.
 */
import type { components } from '@/api/schema'

type S = components['schemas']

// ---------------------------------------------------------------------------
// Pagination + errors
// ---------------------------------------------------------------------------

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface PageParams {
  page?: number
  page_size?: number
}

export interface ApiErrorBody {
  error: {
    code: ApiErrorCode | string
    message: string
    details?: Record<string, unknown>
  }
}

export type ApiErrorCode =
  | 'NOT_FOUND'
  | 'SUBNET_OVERLAP'
  | 'DUPLICATE_CODE'
  | 'DUPLICATE_VLAN_ID'
  | 'VLAN_ID_OUT_OF_RANGE'
  | 'DUPLICATE_IP'
  | 'DUPLICATE_NAME'
  | 'DUPLICATE_PORT'
  | 'DUPLICATE_LINK'
  | 'INVALID_LINK'
  | 'INTEGRITY_VIOLATION'
  | 'NETWORK_ERROR'
  | 'UNKNOWN'

// ---------------------------------------------------------------------------
// Sites
// ---------------------------------------------------------------------------
export type Site = S['SiteRead']
export type SiteCreate = S['SiteCreate']
export type SiteUpdate = S['SiteUpdate']

// ---------------------------------------------------------------------------
// Rooms
// ---------------------------------------------------------------------------
export type Room = S['RoomRead']
export type RoomCreate = S['RoomCreate']
export type RoomUpdate = S['RoomUpdate']

// ---------------------------------------------------------------------------
// VLANs
// ---------------------------------------------------------------------------
export type Vlan = S['VlanRead']
export type VlanCreate = S['VlanCreate']
export type VlanUpdate = S['VlanUpdate']

// ---------------------------------------------------------------------------
// Subnets
// ---------------------------------------------------------------------------
export type Subnet = S['SubnetRead']
export type SubnetCreate = S['SubnetCreate']
export type SubnetUpdate = S['SubnetUpdate']
export type SubnetIpEntry = S['SubnetIpEntry']
export type SubnetIpsResponse = S['SubnetIpsResponse']
export type NextFreeIp = S['NextFreeIpResponse']

// ---------------------------------------------------------------------------
// IPs
// ---------------------------------------------------------------------------
export type Ip = S['IpRead']
export type IpCreate = S['IpCreate']
export type IpUpdate = S['IpUpdate']
export type IpStatus = S['IpStatus']

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------
export type Device = S['DeviceRead']
export type DeviceCreate = S['DeviceCreate']
export type DeviceUpdate = S['DeviceUpdate']
export type DeviceType = S['DeviceType']

// ---------------------------------------------------------------------------
// Switches
// ---------------------------------------------------------------------------
export type Switch = S['SwitchRead']
export type SwitchCreate = S['SwitchCreate']
export type SwitchUpdate = S['SwitchUpdate']

// ---------------------------------------------------------------------------
// Ports
// ---------------------------------------------------------------------------
export type Port = S['PortRead']
export type PortUpdate = S['PortUpdate']
export type PortMode = S['PortMode']
export type PortAdminStatus = S['PortAdminStatus']
export type TaggedVlanAdd = S['TaggedVlanAdd']

// ---------------------------------------------------------------------------
// Links
// ---------------------------------------------------------------------------
export type Link = S['LinkRead']
export type LinkCreate = S['LinkCreate']
export type LinkType = S['LinkType']

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------
export type AuditLog = S['AuditLogRead']
export type AuditAction = S['AuditAction']

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
export type SearchResult = S['SearchResult']
export type SearchResponse = S['SearchResponse']

// ---------------------------------------------------------------------------
// Topology
// ---------------------------------------------------------------------------
export type TopologyNode = S['TopologyNode']
export type TopologyEdge = S['TopologyEdge']
export type TopologyNodeData = S['TopologyNodeData']
export type TopologyEdgeData = S['TopologyEdgeData']
export type TopologyResponse = S['TopologyResponse']

// ---------------------------------------------------------------------------
// Imports
// ---------------------------------------------------------------------------
export type ImportReport = S['ImportReport']
export type ImportErrorRow = S['ImportErrorRow']
