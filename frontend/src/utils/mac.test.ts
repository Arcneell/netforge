import { describe, expect, it } from 'vitest'
import { isValidMac, normalizeMac } from './mac'

describe('isValidMac', () => {
  it('accepts canonical colon-separated MACs', () => {
    expect(isValidMac('aa:bb:cc:dd:ee:ff')).toBe(true)
    expect(isValidMac('00:1A:2b:3C:4d:5E')).toBe(true)
  })

  it('rejects other forms and junk', () => {
    expect(isValidMac('aa-bb-cc-dd-ee-ff')).toBe(false)
    expect(isValidMac('aabb.ccdd.eeff')).toBe(false)
    expect(isValidMac('aa:bb:cc:dd:ee')).toBe(false)
    expect(isValidMac('')).toBe(false)
  })
})

describe('normalizeMac', () => {
  it('normalises the three common forms to lowercase colon notation', () => {
    expect(normalizeMac('AA-BB-CC-DD-EE-FF')).toBe('aa:bb:cc:dd:ee:ff')
    expect(normalizeMac('aabb.ccdd.eeff')).toBe('aa:bb:cc:dd:ee:ff')
    expect(normalizeMac('AABBCCDDEEFF')).toBe('aa:bb:cc:dd:ee:ff')
  })

  it('passes through values that are not 12 hex digits unchanged', () => {
    expect(normalizeMac('')).toBe('')
    expect(normalizeMac('not-a-mac')).toBe('not-a-mac')
    expect(normalizeMac('aa:bb:cc')).toBe('aa:bb:cc')
  })
})
