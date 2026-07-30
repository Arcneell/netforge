import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import { ApiError } from '@/api'
import { useApiErrorMessage } from './useApiErrorMessage'
import { useUiStore } from '@/stores/ui'

// `useToast()` → `useUiStore()` reads the system color scheme on creation
// (`ui.ts::applyTheme`) and jsdom does not implement `matchMedia` at all —
// calling it throws "not a function", not just returning a stub. Every test
// here goes through the store, so the stub is global to the file.
beforeEach(() => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({
      matches: false,
      media: '',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

/** Mount the composable inside a throwaway component so it gets a real Vue
 * app context — `useI18n()` and Pinia's `useUiStore()` both require one. */
function mountComposable() {
  let result!: ReturnType<typeof useApiErrorMessage>
  const pinia = createPinia()
  const Host = defineComponent({
    setup() {
      result = useApiErrorMessage()
      return () => null
    },
  })
  const wrapper = mount(Host, { global: { plugins: [pinia, i18n] } })
  return { result, pinia, wrapper }
}

describe('useApiErrorMessage', () => {
  it('describes a known error code with the localized message', () => {
    const { result } = mountComposable()
    const err = new ApiError(404, 'NOT_FOUND', 'Site 1 does not exist.')
    expect(result.describe(err)).toBe(i18n.global.t('errorCodes.NOT_FOUND'))
  })

  it('falls back to errors.unknown for an unrecognised error code', () => {
    const { result } = mountComposable()
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const err = new ApiError(500, 'SOME_NEW_BACKEND_CODE', 'boom')
    expect(result.describe(err)).toBe(i18n.global.t('errors.unknown'))
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('SOME_NEW_BACKEND_CODE'), 'boom')
    warnSpy.mockRestore()
  })

  it('returns a plain Error message as-is', () => {
    const { result } = mountComposable()
    expect(result.describe(new Error('network exploded'))).toBe('network exploded')
  })

  it('falls back to errors.unknown for a non-Error thrown value', () => {
    const { result } = mountComposable()
    expect(result.describe('just a string')).toBe(i18n.global.t('errors.unknown'))
  })

  it('notify() surfaces a toast and returns the same message describe() would', () => {
    const { result, pinia } = mountComposable()
    const ui = useUiStore(pinia)
    const err = new ApiError(404, 'NOT_FOUND', 'Site 1 does not exist.')

    const message = result.notify(err)

    expect(message).toBe(i18n.global.t('errorCodes.NOT_FOUND'))
    expect(ui.toasts).toHaveLength(1)
    expect(ui.toasts[0].kind).toBe('error')
    expect(ui.toasts[0].message).toBe(message)
  })
})
