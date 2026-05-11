/**
 * Lightweight IPv4/CIDR helpers — purely client-side computation for visual
 * rendering (IpGrid sizing, address list, "next free" hints). All authoritative
 * IP work happens on the backend (PostgreSQL INET/CIDR + GiST), so this module
 * has no need to validate exotic CIDR notations.
 *
 * Throws on malformed input — callers should validate user input upstream.
 */

/** Convert a dotted-quad IPv4 string into its 32-bit integer form. */
export function ipToInt(ip: string): number {
  const parts = ip.split('.')
  if (parts.length !== 4) throw new Error(`Invalid IPv4 address: ${ip}`)
  let n = 0
  for (const p of parts) {
    const o = Number(p)
    if (!Number.isInteger(o) || o < 0 || o > 255) throw new Error(`Invalid octet in ${ip}`)
    n = (n << 8) + o
  }
  // Force unsigned 32-bit (>>> 0) because JS bitwise ops operate on signed int32.
  return n >>> 0
}

export function intToIp(n: number): string {
  return [(n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff].join('.')
}

export interface ParsedCidr {
  network: string
  prefix: number
  networkInt: number
  broadcastInt: number
  /** Total addresses including network + broadcast. */
  total: number
  /** Usable host count: total - 2 for /31..0, 2 for /31 (RFC 3021), 1 for /32. */
  usable: number
}

export function parseCidr(cidr: string): ParsedCidr {
  const [net, prefixStr] = cidr.split('/')
  if (!net || !prefixStr) throw new Error(`Invalid CIDR: ${cidr}`)
  const prefix = Number(prefixStr)
  if (!Number.isInteger(prefix) || prefix < 0 || prefix > 32) {
    throw new Error(`Invalid CIDR prefix: ${cidr}`)
  }
  const hostBits = 32 - prefix
  const networkInt = ipToInt(net)
  // Mask off host bits — caller may pass any IP within the block, we normalize.
  const mask = hostBits === 32 ? 0 : (0xffffffff << hostBits) >>> 0
  const base = (networkInt & mask) >>> 0
  const total = hostBits === 32 ? 1 : 2 ** hostBits
  const broadcastInt = (base + total - 1) >>> 0
  const usable = prefix === 32 ? 1 : prefix === 31 ? 2 : total - 2
  return {
    network: intToIp(base),
    prefix,
    networkInt: base,
    broadcastInt,
    total,
    usable,
  }
}

/**
 * Iterate every address in the block as a dotted-quad string. Hard cap at
 * `max` because /16 = 65k addresses is already enough to choke the DOM if
 * naively rendered — the IpGrid uses a virtualized renderer for big blocks.
 */
export function* iterateCidr(cidr: string, max = 65536): Generator<string> {
  const { networkInt, total } = parseCidr(cidr)
  const count = Math.min(total, max)
  for (let i = 0; i < count; i++) {
    yield intToIp(networkInt + i)
  }
}

export function ipInCidr(ip: string, cidr: string): boolean {
  const { networkInt, broadcastInt } = parseCidr(cidr)
  const n = ipToInt(ip)
  return n >= networkInt && n <= broadcastInt
}

/** Lexicographic sort would mis-order 10.0.0.9 vs 10.0.0.10 — numeric is required. */
export function compareIps(a: string, b: string): number {
  return ipToInt(a) - ipToInt(b)
}
