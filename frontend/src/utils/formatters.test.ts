import { describe, expect, it } from 'vitest'
import { formatBytes, formatDate, formatNumber, formatPercent } from './formatters'

describe('formatBytes', () => {
  it('uses 1024-based units with adaptive precision', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(1024)).toBe('1.0 KiB')
    expect(formatBytes(1536)).toBe('1.5 KiB')
    expect(formatBytes(10 * 1024)).toBe('10 KiB')
    expect(formatBytes(1024 * 1024)).toBe('1.0 MiB')
    expect(formatBytes(5 * 1024 * 1024 * 1024)).toBe('5.0 GiB')
  })

  it('guards against invalid / negative input', () => {
    expect(formatBytes(NaN)).toBe('—')
    expect(formatBytes(-1)).toBe('—')
    expect(formatBytes(Infinity)).toBe('—')
  })
})

describe('formatter null/NaN guards', () => {
  it('returns an em dash for empty or unparseable dates', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate(undefined)).toBe('—')
    expect(formatDate('not-a-date')).toBe('—')
  })

  it('returns an em dash for non-finite numbers', () => {
    expect(formatNumber(NaN)).toBe('—')
    expect(formatPercent(Infinity)).toBe('—')
  })
})
