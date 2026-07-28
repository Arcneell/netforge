import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { i18n } from '@/i18n'
import DataTable, { type DataTableColumn } from './DataTable.vue'

// DataTable deliberately has no client-side sorting/filtering — the dense
// logic worth pinning down is column rendering (desktop table + mobile
// cards from one `columns` array), the row-click contract, and the three
// body states (skeleton, empty, rows).

interface Row {
  id: number
  name: string
  cidr: string
}

const columns: DataTableColumn[] = [
  { key: 'name', label: 'Name' },
  { key: 'cidr', label: 'CIDR', align: 'right' },
  { key: 'actions', label: '' },
]

const rows: Row[] = [
  { id: 1, name: 'core', cidr: '10.0.0.0/24' },
  { id: 2, name: 'lab', cidr: '10.0.30.0/24' },
]

function mountTable(props: Record<string, unknown> = {}) {
  return mount(DataTable, {
    props: { columns, rows, ...props },
    global: { plugins: [i18n] },
  })
}

describe('DataTable', () => {
  it('renders one <th> per column with alignment classes', () => {
    const ths = mountTable().findAll('thead th')
    expect(ths).toHaveLength(3)
    expect(ths[0].text()).toBe('Name')
    expect(ths[0].classes()).toContain('text-left')
    expect(ths[1].text()).toBe('CIDR')
    expect(ths[1].classes()).toContain('text-right')
  })

  it('renders a body row per item, cell values from the column key', () => {
    const trs = mountTable().findAll('tbody tr')
    expect(trs).toHaveLength(2)
    const cells = trs[0].findAll('td').map((td) => td.text())
    expect(cells[0]).toBe('core')
    expect(cells[1]).toBe('10.0.0.0/24')
    // `actions` has no matching row field — falls back to the em dash.
    expect(cells[2]).toBe('—')
  })

  it('mirrors rows into the mobile card list (primary col as title, details as dl)', () => {
    const cards = mountTable().findAll('li')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('core')
    expect(cards[0].find('dt').text()).toBe('CIDR')
    expect(cards[0].find('dd').text()).toBe('10.0.0.0/24')
  })

  it('emits row-click with the row payload only when clickable', async () => {
    const clickable = mountTable({ clickable: true })
    await clickable.find('tbody tr').trigger('click')
    expect(clickable.emitted('row-click')).toHaveLength(1)
    expect(clickable.emitted('row-click')![0]).toEqual([rows[0]])

    const inert = mountTable()
    await inert.find('tbody tr').trigger('click')
    expect(inert.emitted('row-click')).toBeUndefined()
  })

  it('shows the empty state (custom title) when there are no rows', () => {
    const wrapper = mountTable({ rows: [], emptyTitle: 'Nothing here' })
    expect(wrapper.text()).toContain('Nothing here')
  })

  it('shows skeleton rows while loading with no data yet', () => {
    const wrapper = mountTable({ rows: [], loading: true, skeletonRows: 4 })
    expect(wrapper.findAll('tbody tr[aria-busy="true"]')).toHaveLength(4)
    // Skeletons, not the empty state.
    expect(wrapper.text()).not.toContain(i18n.global.t('common.empty.title'))
  })

  it('renders scoped cell slots with row + value props', () => {
    const wrapper = mount(DataTable, {
      props: { columns, rows },
      global: { plugins: [i18n] },
      slots: {
        // The slot prop type is the generic-erased `{ id: string | number }`
        // in the test harness — narrow to Row for the assertion.
        'cell-cidr': ({ row, value }: { row: { id: string | number }; value: unknown }) =>
          `${(row as Row).name}=${value}`,
      },
    })
    expect(wrapper.find('tbody tr').text()).toContain('core=10.0.0.0/24')
  })
})
