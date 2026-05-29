import { describe, expect, it } from 'vitest'
import { compareIps, intToIp, ipInCidr, ipToInt, iterateCidr, parseCidr } from './cidr'

describe('ipToInt / intToIp', () => {
  it('round-trips dotted-quad addresses', () => {
    for (const ip of ['0.0.0.0', '10.0.0.1', '192.168.1.254', '255.255.255.255']) {
      expect(intToIp(ipToInt(ip))).toBe(ip)
    }
  })

  it('treats the high bit as unsigned', () => {
    // 255.x would overflow into a negative int32 without the >>> 0 guard.
    expect(ipToInt('255.255.255.255')).toBe(4294967295)
  })

  it('throws on malformed input', () => {
    expect(() => ipToInt('10.0.0')).toThrow()
    expect(() => ipToInt('10.0.0.256')).toThrow()
    expect(() => ipToInt('10.0.0.x')).toThrow()
  })
})

describe('parseCidr', () => {
  it('normalises a host address down to its network', () => {
    const p = parseCidr('10.0.30.55/24')
    expect(p.network).toBe('10.0.30.0')
    expect(p.prefix).toBe(24)
    expect(p.total).toBe(256)
    expect(p.usable).toBe(254)
  })

  it('applies RFC 3021 (/31) and host (/32) usable-count rules', () => {
    expect(parseCidr('10.0.0.0/31').usable).toBe(2)
    expect(parseCidr('10.0.0.5/32').usable).toBe(1)
    expect(parseCidr('10.0.0.5/32').total).toBe(1)
  })

  it('computes bounds for a small block', () => {
    const p = parseCidr('192.168.1.0/30')
    expect(p.total).toBe(4)
    expect(p.networkInt).toBe(ipToInt('192.168.1.0'))
    expect(p.broadcastInt).toBe(ipToInt('192.168.1.3'))
    expect(p.usable).toBe(2)
  })

  it('throws on an out-of-range prefix', () => {
    expect(() => parseCidr('10.0.0.0/33')).toThrow()
    expect(() => parseCidr('10.0.0.0')).toThrow()
  })
})

describe('ipInCidr', () => {
  it('includes network and broadcast bounds, excludes neighbours', () => {
    expect(ipInCidr('10.0.30.0', '10.0.30.0/24')).toBe(true)
    expect(ipInCidr('10.0.30.255', '10.0.30.0/24')).toBe(true)
    expect(ipInCidr('10.0.31.0', '10.0.30.0/24')).toBe(false)
    expect(ipInCidr('10.0.29.255', '10.0.30.0/24')).toBe(false)
  })
})

describe('iterateCidr', () => {
  it('yields every address in order', () => {
    expect([...iterateCidr('10.0.0.0/30')]).toEqual([
      '10.0.0.0',
      '10.0.0.1',
      '10.0.0.2',
      '10.0.0.3',
    ])
  })

  it('caps output at the max even for a huge block', () => {
    let count = 0
    for (const _ of iterateCidr('10.0.0.0/8', 5)) count++
    expect(count).toBe(5)
  })
})

describe('compareIps', () => {
  it('orders numerically, not lexicographically', () => {
    const sorted = ['10.0.0.10', '10.0.0.9', '10.0.0.2'].sort(compareIps)
    expect(sorted).toEqual(['10.0.0.2', '10.0.0.9', '10.0.0.10'])
  })
})
