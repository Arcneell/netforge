import { describe, expect, it, vi, beforeEach } from 'vitest'

// Mocked at the module boundary so the assertions are about the URL this
// client builds, not about HTTP.
const request = vi.fn((_config: { url: string }) => Promise.resolve({ nodes: [], edges: [] }))
vi.mock('@/api/client', () => ({ request: (config: { url: string }) => request(config) }))

const { topologyApi } = await import('@/api/endpoints/topology')

/** URL of the single request the call under test issued. */
function urlOf(): string {
  const [first] = request.mock.calls
  if (!first) throw new Error('expected exactly one request')
  return first[0].url
}

describe('topologyApi.get', () => {
  beforeEach(() => request.mockClear())

  it('hits the bare endpoint when no filter is set', async () => {
    await topologyApi.get()
    expect(urlOf()).toBe('/topology')
  })

  it('omits falsy ids rather than sending site_id=0', async () => {
    // 0 is the "all sites" sentinel the select binds to. Forwarding it would
    // filter on a site id that cannot exist and return an empty graph.
    await topologyApi.get({ siteId: 0, roomId: null, vlanId: undefined })
    expect(urlOf()).toBe('/topology')
  })

  it('forwards each filter it was given', async () => {
    await topologyApi.get({ siteId: 3, roomId: 7, vlanId: 42 })
    const url = urlOf()
    expect(url).toContain('site_id=3')
    expect(url).toContain('room_id=7')
    expect(url).toContain('vlan_id=42')
  })

  it('only sends include_devices when it is explicitly off', async () => {
    // The backend default is on, so the common case should not carry the
    // parameter at all.
    await topologyApi.get({ includeDevices: true })
    expect(urlOf()).toBe('/topology')

    request.mockClear()
    await topologyApi.get({ includeDevices: false })
    expect(urlOf()).toContain('include_devices=false')
  })
})
