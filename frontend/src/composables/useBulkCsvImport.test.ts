import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/i18n'
import type { DetectReport } from '@/api'
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
import { BULK_MAX_FILES, BULK_MAX_PER_FILE, useBulkCsvImport } from './useBulkCsvImport'

const mockedImportsApi = vi.mocked(importsApi)

// Same jsdom gap as useApiErrorMessage.test.ts: useToast() -> useUiStore()
// reads matchMedia on creation.
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
  mockedImportsApi.detect.mockReset()
  mockedImportsApi.upload.mockReset()
  mockedImportsApi.uploadBulk.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function csvFile(name = 'sites.csv', size = 10): File {
  return new File([new Uint8Array(size)], name, { type: 'text/csv' })
}

function mountComposable() {
  let result!: ReturnType<typeof useBulkCsvImport>
  const pinia = createPinia()
  const Host = defineComponent({
    setup() {
      result = useBulkCsvImport()
      return () => null
    },
  })
  const wrapper = mount(Host, { global: { plugins: [pinia, i18n] } })
  return { result, pinia, wrapper }
}

const detectReport = (entity: DetectReport['entity'] = 'sites'): DetectReport => ({
  entity,
  confidence: 0.9,
  headers: ['code', 'name'],
  matched_required: ['code', 'name'],
  missing_required: [],
  unknown_headers: [],
  candidates: {},
})

describe('useBulkCsvImport', () => {
  it('rejects a file that is neither .csv nor .zip, without adding it', async () => {
    mockedImportsApi.detect.mockResolvedValue(detectReport())
    const { result, pinia } = mountComposable()

    await result.addFiles([new File(['x'], 'notes.txt', { type: 'text/plain' })])

    expect(result.files.value).toHaveLength(0)
    const ui = useUiStore(pinia)
    expect(ui.toasts[0].kind).toBe('error')
    expect(mockedImportsApi.detect).not.toHaveBeenCalled()
  })

  it('rejects a file over the per-file size limit', async () => {
    const { result, pinia } = mountComposable()
    const tooBig = csvFile('big.csv', BULK_MAX_PER_FILE + 1)

    await result.addFiles([tooBig])

    expect(result.files.value).toHaveLength(0)
    expect(useUiStore(pinia).toasts[0].kind).toBe('error')
  })

  it('accepts a csv file and runs client-side detection on it', async () => {
    mockedImportsApi.detect.mockResolvedValue(detectReport('sites'))
    const { result } = mountComposable()

    await result.addFiles([csvFile()])
    await flushPromises()

    expect(result.files.value).toHaveLength(1)
    expect(mockedImportsApi.detect).toHaveBeenCalledTimes(1)
    expect(result.files.value[0].detection?.entity).toBe('sites')
    expect(result.files.value[0].detecting).toBe(false)
  })

  it('skips client-side detection for .zip files', async () => {
    const { result } = mountComposable()

    await result.addFiles([new File(['x'], 'bundle.zip', { type: 'application/zip' })])

    expect(result.files.value).toHaveLength(1)
    expect(mockedImportsApi.detect).not.toHaveBeenCalled()
    expect(result.files.value[0].detection).toBeNull()
  })

  it('records a per-file detection failure without dropping the slot', async () => {
    mockedImportsApi.detect.mockRejectedValue(new Error('backend unreachable'))
    const { result } = mountComposable()

    await result.addFiles([csvFile()])
    await flushPromises()

    expect(result.files.value).toHaveLength(1)
    expect(result.files.value[0].detectError).toBe('backend unreachable')
  })

  it('stops accepting files once BULK_MAX_FILES is reached', async () => {
    mockedImportsApi.detect.mockResolvedValue(detectReport())
    const { result, pinia } = mountComposable()

    const many = Array.from({ length: BULK_MAX_FILES + 3 }, (_, i) => csvFile(`f${i}.csv`))
    await result.addFiles(many)
    await flushPromises()

    expect(result.files.value).toHaveLength(BULK_MAX_FILES)
    expect(useUiStore(pinia).toasts.some((t) => t.kind === 'error')).toBe(true)
  })

  it('removeSlot / clear reset local state', async () => {
    mockedImportsApi.detect.mockResolvedValue(detectReport())
    const { result } = mountComposable()
    await result.addFiles([csvFile('a.csv'), csvFile('b.csv')])
    await flushPromises()

    result.removeSlot(0)
    expect(result.files.value).toHaveLength(1)
    expect(result.files.value[0].file.name).toBe('b.csv')

    result.clear()
    expect(result.files.value).toHaveLength(0)
    expect(result.report.value).toBeNull()
  })

  it('canSubmit is false with no files and true once a non-detecting file is present', async () => {
    mockedImportsApi.detect.mockResolvedValue(detectReport())
    const { result } = mountComposable()
    expect(result.canSubmit.value).toBe(false)

    await result.addFiles([csvFile()])
    await flushPromises()
    expect(result.canSubmit.value).toBe(true)
  })

  it('submit() posts the batch and stores the report on success', async () => {
    mockedImportsApi.detect.mockResolvedValue(detectReport())
    mockedImportsApi.uploadBulk.mockResolvedValue({
      files: [
        {
          filename: 'sites.csv',
          detected_entity: 'sites',
          parsed_rows: 2,
          ok_rows: 2,
          error_rows: [],
        },
      ],
      total_parsed_rows: 2,
      total_ok_rows: 2,
      applied: true,
    })
    const { result } = mountComposable()
    await result.addFiles([csvFile()])
    await flushPromises()

    await result.submit()

    expect(mockedImportsApi.uploadBulk).toHaveBeenCalledWith([expect.any(File)], true)
    expect(result.report.value?.applied).toBe(true)
    expect(result.submitting.value).toBe(false)
  })

  it('submit() surfaces a toast and clears submitting on failure', async () => {
    mockedImportsApi.detect.mockResolvedValue(detectReport())
    mockedImportsApi.uploadBulk.mockRejectedValue(new Error('server exploded'))
    const { result, pinia } = mountComposable()
    await result.addFiles([csvFile()])
    await flushPromises()

    await result.submit()

    expect(result.report.value).toBeNull()
    expect(result.submitting.value).toBe(false)
    expect(useUiStore(pinia).toasts.some((t) => t.message === 'server exploded')).toBe(true)
  })
})
