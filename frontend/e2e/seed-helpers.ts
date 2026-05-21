import type { APIRequestContext } from '@playwright/test'

/**
 * Idempotent seed helpers — each spec calls these at start to guarantee the
 * entities it drives through the UI exist. Codex flagged on PR #7 that the
 * specs assumed leftover dev data; this module makes them DB-agnostic.
 *
 * All helpers POST through the real API using the storage state's session
 * cookie, so they exercise the same auth + validation path a UI write would.
 * 409 / overlap errors are swallowed: the helper succeeds either way because
 * the post-condition (entity exists) is what we care about.
 */

const E2E_SITE_CODE = 'E2E'
const E2E_SUBNET_CIDR = '10.250.0.0/24'

interface Site {
  id: number
  code: string
  name: string
}

interface Subnet {
  id: number
  cidr: string
  site_id: number
}

interface Switch {
  id: number
  name: string
  port_count: number
}

interface Port {
  id: number
  switch_id: number
  number: number
}

async function findByList<T extends { id: number }>(
  request: APIRequestContext,
  url: string,
  match: (item: T) => boolean,
): Promise<T | null> {
  const res = await request.get(url)
  if (!res.ok()) return null
  const body = (await res.json()) as { items: T[] }
  return body.items.find(match) ?? null
}

export async function ensureSite(request: APIRequestContext): Promise<Site> {
  const existing = await findByList<Site>(
    request,
    '/api/sites?page_size=200',
    (s) => s.code === E2E_SITE_CODE,
  )
  if (existing) return existing
  const res = await request.post('/api/sites', {
    data: { code: E2E_SITE_CODE, name: 'E2E sandbox' },
  })
  if (!res.ok()) throw new Error(`ensureSite failed: ${res.status()} ${await res.text()}`)
  return res.json()
}

export async function ensureSubnet(request: APIRequestContext): Promise<Subnet> {
  const site = await ensureSite(request)
  const existing = await findByList<Subnet>(
    request,
    '/api/subnets?page_size=200',
    (s) => s.cidr === E2E_SUBNET_CIDR,
  )
  if (existing) return existing
  const res = await request.post('/api/subnets', {
    data: {
      cidr: E2E_SUBNET_CIDR,
      site_id: site.id,
      description: 'E2E test subnet',
      dhcp_enabled: false,
    },
  })
  if (!res.ok()) throw new Error(`ensureSubnet failed: ${res.status()} ${await res.text()}`)
  return res.json()
}

/**
 * Create a fresh switch with a timestamped name. Not idempotent on purpose —
 * each topology run gets its own pair so the link constraint (unique
 * port-pair) is satisfied even when DB state accumulates.
 */
export async function createSwitch(
  request: APIRequestContext,
  name: string,
  portCount = 4,
): Promise<Switch> {
  const res = await request.post('/api/switches', {
    data: { name, port_count: portCount },
  })
  if (!res.ok()) throw new Error(`createSwitch failed: ${res.status()} ${await res.text()}`)
  return res.json()
}

export async function getFirstPort(request: APIRequestContext, switchId: number): Promise<Port> {
  const res = await request.get(`/api/switches/${switchId}/ports?page_size=1`)
  if (!res.ok()) throw new Error(`getFirstPort failed: ${res.status()} ${await res.text()}`)
  const body = (await res.json()) as { items: Port[] }
  if (body.items.length === 0) throw new Error(`switch ${switchId} has no ports`)
  return body.items[0]
}

export async function ensureLink(
  request: APIRequestContext,
  portAId: number,
  portBId: number,
): Promise<void> {
  const res = await request.post('/api/links', {
    data: { port_a_id: portAId, port_b_id: portBId, link_type: 'copper' },
  })
  // 409/422 means the link already exists between these ports — fine, the
  // post-condition is met. Anything else is a real failure.
  if (!res.ok() && res.status() !== 409 && res.status() !== 422) {
    throw new Error(`ensureLink failed: ${res.status()} ${await res.text()}`)
  }
}

/**
 * Topology fixture: two fresh switches with a link between port #1 of each.
 * Names are timestamp-suffixed so concurrent / repeat runs don't collide on
 * the unique switch-name constraint.
 */
export async function seedTopologyPair(
  request: APIRequestContext,
): Promise<{ a: Switch; b: Switch }> {
  const stamp = Date.now()
  const a = await createSwitch(request, `E2E-TOPO-A-${stamp}`)
  const b = await createSwitch(request, `E2E-TOPO-B-${stamp}`)
  const [pa, pb] = await Promise.all([getFirstPort(request, a.id), getFirstPort(request, b.id)])
  await ensureLink(request, pa.id, pb.id)
  return { a, b }
}
