import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import { useUiStore } from '@/stores/ui'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    importsApi: {
      detect: vi.fn(),
      upload: vi.fn(),
      uploadBulk: vi.fn(),
    },
  }
})

import { importsApi } from '@/api'
import { useSingleCsvImport } from './useSingleCsvImport'

const mockedImportsApi = vi.mocked(importsApi)

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
  mockedImportsApi.upload.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function csvFile(name = 'sites.csv'): File {
  return new File(['code,name\nHQ,Headquarters'], name, { type: 'text/csv' })
}

function mountComposable() {
  let result!: ReturnType<typeof useSingleCsvImport>
  const pinia = createPinia()
  const Host = defineComponent({
    setup() {
      result = useSingleCsvImport()
      return () => null
    },
  })
  const wrapper = mount(Host, { global: { plugins: [pinia, i18n] } })
  return { result, pinia, wrapper }
}

describe('useSingleCsvImport', () => {
  it('defaults to the sites entity with dry-run on', () => {
    const { result } = mountComposable()
    expect(result.entity.value).toBe('sites')
    expect(result.dryRun.value).toBe(true)
    expect(result.file.value).toBeNull()
  })

  it('submit() is a no-op when no file is selected', async () => {
    const { result } = mountComposable()
    await result.submit()
    expect(mockedImportsApi.upload).not.toHaveBeenCalled()
  })

  it('submit() uploads the file for the current entity and stores the report', async () => {
    mockedImportsApi.upload.mockResolvedValue({
      parsed_rows: 1,
      ok_rows: 1,
      error_rows: [],
      applied: true,
    })
    const { result } = mountComposable()
    result.file.value = csvFile()
    result.entity.value = 'rooms'

    await result.submit()

    expect(mockedImportsApi.upload).toHaveBeenCalledWith(
      'rooms',
      result.file.value,
      true,
      undefined,
    )
    expect(result.report.value?.applied).toBe(true)
    expect(result.lastEntity.value).toBe('rooms')
    expect(result.submitting.value).toBe(false)
  })

  it('forwards a pending column mapping only when it matches the current entity', async () => {
    mockedImportsApi.upload.mockResolvedValue({
      parsed_rows: 1,
      ok_rows: 1,
      error_rows: [],
      applied: false,
    })
    const { result } = mountComposable()
    result.applyMapping({ Nom: 'name' }, 'devices')
    // applyMapping auto-switches the entity dropdown to match the mapping.
    expect(result.entity.value).toBe('devices')
    result.file.value = csvFile('devices.csv')

    await result.submit()

    expect(mockedImportsApi.upload).toHaveBeenCalledWith('devices', result.file.value, true, {
      Nom: 'name',
    })
    // Single-shot: the mapping is cleared after being consumed.
    expect(result.pendingMapping.value).toBeNull()
    expect(result.pendingMappingEntity.value).toBeNull()
  })

  it('does not forward a stale mapping prepared for a different entity', async () => {
    mockedImportsApi.upload.mockResolvedValue({
      parsed_rows: 1,
      ok_rows: 1,
      error_rows: [],
      applied: false,
    })
    const { result } = mountComposable()
    result.applyMapping({ Nom: 'name' }, 'devices')
    // Operator switches away from the entity the mapping was built for.
    result.entity.value = 'sites'
    result.file.value = csvFile()

    await result.submit()

    expect(mockedImportsApi.upload).toHaveBeenCalledWith(
      'sites',
      result.file.value,
      true,
      undefined,
    )
  })

  it('submit() surfaces a toast on failure and clears submitting', async () => {
    mockedImportsApi.upload.mockRejectedValue(new Error('boom'))
    const { result, pinia } = mountComposable()
    result.file.value = csvFile()

    await result.submit()

    expect(result.report.value).toBeNull()
    expect(result.submitting.value).toBe(false)
    expect(useUiStore(pinia).toasts.some((t) => t.message === 'boom')).toBe(true)
  })
})
