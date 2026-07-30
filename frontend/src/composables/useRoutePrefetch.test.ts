import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// `useRoutePrefetch` imports the app router purely to resolve a path to its
// route records. Mocking it keeps these tests off the real 32-route table (and
// off the 32 dynamic imports resolving it would trigger) and lets each case
// state exactly which loaders a path maps to.
const resolve = vi.fn()
vi.mock('@/router', () => ({ router: { resolve: (path: string) => resolve(path) } }))

import { prefetchRoute, prefetchRoutesWhenIdle, resetPrefetchCache } from './useRoutePrefetch'

/** Route record shaped the way Vue Router hands them back from `resolve`. */
function record(components: Record<string, unknown>) {
  return { components }
}

beforeEach(() => {
  resetPrefetchCache()
  resolve.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('prefetchRoute', () => {
  it('calls the lazy loader for every matched record', () => {
    const shell = vi.fn().mockResolvedValue({})
    const view = vi.fn().mockResolvedValue({})
    resolve.mockReturnValue({ matched: [record({ default: shell }), record({ default: view })] })

    prefetchRoute('/subnets')

    expect(shell).toHaveBeenCalledTimes(1)
    expect(view).toHaveBeenCalledTimes(1)
  })

  it('only loads a path once however many times it is hovered', () => {
    const view = vi.fn().mockResolvedValue({})
    resolve.mockReturnValue({ matched: [record({ default: view })] })

    prefetchRoute('/subnets')
    prefetchRoute('/subnets')
    prefetchRoute('/subnets')

    expect(view).toHaveBeenCalledTimes(1)
  })

  it('keeps separate paths separate', () => {
    const a = vi.fn().mockResolvedValue({})
    const b = vi.fn().mockResolvedValue({})
    resolve.mockImplementation((path: string) => ({
      matched: [record({ default: path === '/a' ? a : b })],
    }))

    prefetchRoute('/a')
    prefetchRoute('/b')

    expect(a).toHaveBeenCalledTimes(1)
    expect(b).toHaveBeenCalledTimes(1)
  })

  it('retries after a failed load rather than caching the failure', async () => {
    const view = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({})
    resolve.mockReturnValue({ matched: [record({ default: view })] })

    prefetchRoute('/subnets')
    // Let the rejection settle so the path is dropped from the cache.
    await Promise.resolve()
    await Promise.resolve()
    prefetchRoute('/subnets')

    expect(view).toHaveBeenCalledTimes(2)
  })

  it('does not throw when the path cannot be resolved', () => {
    resolve.mockImplementation(() => {
      throw new Error('No match for /nope')
    })

    expect(() => prefetchRoute('/nope')).not.toThrow()
  })

  it('ignores an eagerly-imported component', () => {
    // A non-lazy route stores the component object itself. There is nothing to
    // load, and it must not be called.
    resolve.mockReturnValue({ matched: [record({ default: { name: 'EagerView' } })] })

    expect(() => prefetchRoute('/eager')).not.toThrow()
  })

  it('survives a loader that throws synchronously', () => {
    const boom = vi.fn(() => {
      throw new Error('bad loader')
    })
    resolve.mockReturnValue({ matched: [record({ default: boom })] })

    expect(() => prefetchRoute('/boom')).not.toThrow()
    expect(boom).toHaveBeenCalledTimes(1)
  })

  it('tolerates a record with no components', () => {
    resolve.mockReturnValue({ matched: [{ components: null }] })

    expect(() => prefetchRoute('/empty')).not.toThrow()
  })
})

describe('prefetchRoutesWhenIdle', () => {
  /** Runs idle callbacks synchronously so the queue drains inside the test. */
  function stubIdleCallback() {
    vi.stubGlobal(
      'requestIdleCallback',
      vi.fn((cb: () => void) => {
        cb()
        return 1
      }),
    )
  }

  it('warms every path given to it', () => {
    stubIdleCallback()
    const loaders = new Map<string, ReturnType<typeof vi.fn>>()
    resolve.mockImplementation((path: string) => {
      if (!loaders.has(path)) loaders.set(path, vi.fn().mockResolvedValue({}))
      return { matched: [record({ default: loaders.get(path) })] }
    })

    prefetchRoutesWhenIdle(['/a', '/b', '/c'])

    expect([...loaders.keys()].sort()).toEqual(['/a', '/b', '/c'])
    for (const loader of loaders.values()) expect(loader).toHaveBeenCalledTimes(1)
  })

  it('does nothing for an empty list', () => {
    stubIdleCallback()
    prefetchRoutesWhenIdle([])
    expect(resolve).not.toHaveBeenCalled()
  })

  it('skips speculative work when the user asked to save data', () => {
    stubIdleCallback()
    vi.stubGlobal('navigator', { connection: { saveData: true } })

    prefetchRoutesWhenIdle(['/a', '/b'])

    expect(resolve).not.toHaveBeenCalled()
  })

  it.each(['slow-2g', '2g'])('skips speculative work on a %s connection', (effectiveType) => {
    stubIdleCallback()
    vi.stubGlobal('navigator', { connection: { saveData: false, effectiveType } })

    prefetchRoutesWhenIdle(['/a'])

    expect(resolve).not.toHaveBeenCalled()
  })

  it('still prefetches on a fast connection', () => {
    stubIdleCallback()
    vi.stubGlobal('navigator', { connection: { saveData: false, effectiveType: '4g' } })
    resolve.mockReturnValue({ matched: [record({ default: vi.fn().mockResolvedValue({}) })] })

    prefetchRoutesWhenIdle(['/a'])

    expect(resolve).toHaveBeenCalledWith('/a')
  })

  it('falls back to a timeout where requestIdleCallback is missing', () => {
    // Safari shipped requestIdleCallback only in 17.
    vi.useFakeTimers()
    vi.stubGlobal('requestIdleCallback', undefined)
    resolve.mockReturnValue({ matched: [record({ default: vi.fn().mockResolvedValue({}) })] })

    prefetchRoutesWhenIdle(['/a'])
    expect(resolve).not.toHaveBeenCalled()

    vi.runOnlyPendingTimers()
    expect(resolve).toHaveBeenCalledWith('/a')
  })

  it('does not re-warm a path already prefetched by hover', () => {
    stubIdleCallback()
    const view = vi.fn().mockResolvedValue({})
    resolve.mockReturnValue({ matched: [record({ default: view })] })

    prefetchRoute('/a')
    prefetchRoutesWhenIdle(['/a'])

    expect(view).toHaveBeenCalledTimes(1)
  })
})
