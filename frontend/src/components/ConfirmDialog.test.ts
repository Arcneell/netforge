import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { i18n } from '@/i18n'
import ConfirmDialog from './ConfirmDialog.vue'

// ConfirmDialog wraps Modal, which <Teleport>s its content to <body> — the
// rendered dialog lives outside `wrapper.element`, so assertions query
// `document.body` directly (real DOM, real click()) rather than
// `wrapper.find`. `wrapper.emitted()` still works: it's tracked on the
// component instance, independent of where its DOM landed.

let mounted: VueWrapper[] = []

function mountDialog(props: Record<string, unknown> = {}) {
  const wrapper = mount(ConfirmDialog, {
    props: { open: true, title: 'Delete site', message: 'Are you sure?', ...props },
    global: { plugins: [i18n] },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  return wrapper
}

function findButtonByText(text: string): HTMLButtonElement | undefined {
  return Array.from(document.querySelectorAll('button')).find((b) => b.textContent?.trim() === text)
}

afterEach(() => {
  for (const w of mounted) w.unmount()
  mounted = []
})

describe('ConfirmDialog', () => {
  it('renders the title and message when open', () => {
    mountDialog()
    expect(document.querySelector('[role="dialog"]')).not.toBeNull()
    expect(document.body.textContent).toContain('Delete site')
    expect(document.body.textContent).toContain('Are you sure?')
  })

  it('renders nothing when closed', () => {
    mountDialog({ open: false })
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })

  it('emits confirm when the confirm button is clicked', async () => {
    const wrapper = mountDialog()
    findButtonByText(i18n.global.t('common.confirm'))?.click()
    await flushPromises()
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    expect(wrapper.emitted('cancel')).toBeUndefined()
  })

  it('emits cancel when the cancel button is clicked', async () => {
    const wrapper = mountDialog()
    findButtonByText(i18n.global.t('common.cancel'))?.click()
    await flushPromises()
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(wrapper.emitted('confirm')).toBeUndefined()
  })

  it('emits cancel when the modal close (X) button is clicked', async () => {
    const wrapper = mountDialog()
    const closeBtn = document.querySelector('[aria-label]') as HTMLButtonElement | null
    // The header close button is the only [aria-label] button when no other
    // aria-labelled control is in the slot content for this fixture.
    closeBtn?.click()
    await flushPromises()
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('uses custom labels and variant when provided', () => {
    mountDialog({ confirmLabel: 'Delete', cancelLabel: 'Keep', variant: 'danger' })
    expect(findButtonByText('Delete')).toBeTruthy()
    expect(findButtonByText('Keep')).toBeTruthy()
  })

  it('disables both buttons while loading', () => {
    mountDialog({ loading: true })
    const confirmBtn = findButtonByText(i18n.global.t('common.confirm'))
    const cancelBtn = findButtonByText(i18n.global.t('common.cancel'))
    expect(confirmBtn?.disabled).toBe(true)
    expect(cancelBtn?.disabled).toBe(true)
  })
})
