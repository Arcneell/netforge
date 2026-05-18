export { api, request, registerApiHooks, ApiError } from './client'
export type { ApiHooks } from './client'

export { authApi } from './endpoints/auth'
export type {
  CurrentUser,
  UserRole,
  ApiToken,
  ApiTokenCreate,
  ApiTokenCreated,
} from './endpoints/auth'

export { healthApi } from './endpoints/health'
export type { HealthResponse } from './endpoints/health'

export { sitesApi } from './endpoints/sites'
export { roomsApi, type RoomFilters } from './endpoints/rooms'
export { vlansApi } from './endpoints/vlans'
export { subnetsApi, type SubnetFilters } from './endpoints/subnets'
export { ipsApi, type IpFilters } from './endpoints/ips'
export { devicesApi, type DeviceFilters } from './endpoints/devices'
export { switchesApi, type SwitchFilters } from './endpoints/switches'
export { portsApi } from './endpoints/ports'
export {
  linksApi,
  type LinkFilters,
  type LinkCreateByName,
  type LinkUpdate,
} from './endpoints/links'
export { auditApi, type AuditFilters } from './endpoints/audit'
export {
  searchApi,
  type SearchResult,
  type SearchResponse,
  type SearchResultType,
} from './endpoints/search'
export { topologyApi } from './endpoints/topology'
export {
  importsApi,
  IMPORT_ENTITIES,
  type ImportEntity,
  type DetectReport,
  type BulkImportFileReport,
  type BulkImportReport,
} from './endpoints/imports'

export type * from './types'
