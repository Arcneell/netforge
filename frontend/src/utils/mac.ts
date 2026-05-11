const MAC_RE = /^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$/

export function isValidMac(mac: string): boolean {
  return MAC_RE.test(mac)
}

/**
 * Normalize a MAC to lowercase `aa:bb:cc:dd:ee:ff`.
 * Accepts the three common forms (colons, dashes, dots) and any case.
 * Returns the input unchanged if it doesn't look like a MAC at all,
 * so it can be safely fed pass-through values like "" or null-coerced text.
 */
export function normalizeMac(input: string): string {
  const stripped = input.replace(/[^0-9a-fA-F]/g, '').toLowerCase()
  if (stripped.length !== 12) return input
  return stripped.match(/.{1,2}/g)!.join(':')
}
