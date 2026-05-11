export { api, request, registerApiHooks, ApiError } from './client'
export type { ApiHooks } from './client'

export { authApi } from './endpoints/auth'
export type { CurrentUser, UserRole } from './endpoints/auth'

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
export { linksApi, type LinkFilters } from './endpoints/links'
export { auditApi, type AuditFilters } from './endpoints/audit'
export { searchApi } from './endpoints/search'

export type * from './types'
