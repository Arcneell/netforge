import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from './auth'

const KEY = 'netforge.postLoginPath'

describe('auth store — post-login path sanitisation (open-redirect defence)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
  })

  function consume(raw: string): string | null {
    sessionStorage.setItem(KEY, raw)
    return useAuthStore().consumePostLoginPath()
  }

  it('accepts internal absolute paths', () => {
    expect(consume('/subnets')).toBe('/subnets')
    expect(consume('/subnets/12?tab=ips')).toBe('/subnets/12?tab=ips')
    // A colon AFTER the query separator is not a scheme — must be allowed.
    expect(consume('/search?q=a:b')).toBe('/search?q=a:b')
  })

  it('rejects protocol-relative and scheme-bearing URLs', () => {
    expect(consume('//evil.com')).toBeNull()
    expect(consume('https://evil.com')).toBeNull()
    expect(consume('javascript:alert(1)')).toBeNull()
    expect(consume('/path:with-colon')).toBeNull()
  })

  it('rejects backslash paths and control / newline chars (CRLF injection)', () => {
    expect(consume('/foo\\bar')).toBeNull()
    expect(consume('/foo\nSet-Cookie: x')).toBeNull()
    expect(consume('/foo\r\nbar')).toBeNull()
  })

  it('rejects non-path input and over-long values', () => {
    expect(consume('relative')).toBeNull()
    expect(consume('/' + 'a'.repeat(2001))).toBeNull()
  })

  it('consumes (clears) the stored value', () => {
    sessionStorage.setItem(KEY, '/subnets')
    useAuthStore().consumePostLoginPath()
    expect(sessionStorage.getItem(KEY)).toBeNull()
  })
})
