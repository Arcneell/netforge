<script setup lang="ts" generic="T extends { id: number | string }">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Inbox, ChevronRight } from 'lucide-vue-next'
import EmptyState from '@/components/EmptyState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'

/**
 * Minimal accessible table with explicit column slots and one row-click event.
 * No client-side sorting, filtering, or virtualization on purpose — those
 * concerns belong to the parent page so it can push them down to the API.
 *
 * Responsive: on screens narrower than `md` the table is replaced by a stack
 * of cards. The first non-actions column is used as the card title, the
 * `actions` column is rendered as the footer button row, and every other
 * column becomes a label/value pair inside the card.
 */
// `T = Record<string, unknown>` default lets call sites keep writing
// `DataTableColumn[]` (as every list view does today) without pinning the
// row type at the column-declaration site.
export interface DataTableColumn<T = Record<string, unknown>> {
  // Real columns key into the row (`keyof T`); "actions" and any other
  // synthetic, non-data column need `string` too since they don't exist on
  // `T` at all. The union still catches typos in the common case (an IDE
  // will offer `keyof T` completions) while keeping "actions" legal.
  //
  // NB: deliberately `keyof T`, not `Extract<keyof T, string>` — wrapping
  // it in a conditional/mapped-type helper here blocks Vue's generic type
  // inference for `T` from this prop across every list view (every `row`
  // in every `cell-*` slot degrades to the bare `{ id: string | number }`
  // constraint instead of the real row type). `String(col.key)` at the two
  // template call sites that build a slot *name* handles the leftover
  // `number | symbol` case instead.
  key: keyof T | string
  label: string
  /** Tailwind classes applied to <th> and each <td>. */
  cellClass?: string
  /** Right-align numeric columns. */
  align?: 'left' | 'right' | 'center'
  /** Hide on narrow screens (desktop table only — the mobile cards ignore this). */
  hideOnSm?: boolean
  /** Hide on mobile cards (useful for redundant columns like a separate name field). */
  hideOnMobile?: boolean
}

const props = withDefaults(
  defineProps<{
    columns: DataTableColumn<T>[]
    rows: T[]
    loading?: boolean
    /** Title shown in the empty-state when there are zero rows. */
    emptyTitle?: string
    emptyDescription?: string
    /** Adds a hover style + cursor on rows when truthy. */
    clickable?: boolean
    /** Skeleton rows rendered during the first load (no rows yet). */
    skeletonRows?: number
    /** Extra classes for a specific row, e.g. a temporary highlight ring
     *  for the row a deep link (like GlobalSearch) landed on. Returning ''
     *  for every other row keeps this a no-op by default. */
    rowClass?: (row: T) => string
  }>(),
  {
    loading: false,
    emptyTitle: undefined,
    emptyDescription: undefined,
    clickable: false,
    skeletonRows: 6,
    rowClass: undefined,
  },
)

defineEmits<{
  (e: 'row-click', row: T): void
}>()

const { t } = useI18n()

function alignClass(a: DataTableColumn<T>['align']): string {
  if (a === 'right') return 'text-right'
  if (a === 'center') return 'text-center'
  return 'text-left'
}

// Card layout: split columns into title / actions / details. The "primary"
// column is the first non-actions column (typically `name`, `cidr`, etc.).
const primaryCol = computed<DataTableColumn<T> | null>(
  () => props.columns.find((c) => c.key !== 'actions') ?? null,
)
const actionsCol = computed<DataTableColumn<T> | null>(
  () => props.columns.find((c) => c.key === 'actions') ?? null,
)
const detailCols = computed<DataTableColumn<T>[]>(() =>
  props.columns.filter(
    (c) => c.key !== 'actions' && c.key !== primaryCol.value?.key && !c.hideOnMobile,
  ),
)

/**
 * Cell accessor. `col.key` is typed `keyof T | string` so synthetic columns
 * like "actions" (present on every list page, absent from every row type)
 * still type-check — but that union means TS can't index `row` with it
 * directly without a cast. Centralising the cast here replaces the seven
 * `(row as any)[col.key]` call sites this component used to have, each of
 * which silenced type-checking for the *whole* expression instead of just
 * the index access that actually needs it.
 */
function cellValue(row: T, key: DataTableColumn<T>['key']): unknown {
  return (row as unknown as Record<string, unknown>)[key as string]
}
</script>

<template>
  <div class="nf-card overflow-hidden">
    <!-- Desktop / tablet: classic table -->
    <div class="relative overflow-x-auto hidden md:block">
      <table class="w-full text-sm">
        <thead>
          <tr>
            <th
              v-for="col in columns"
              :key="col.key"
              :class="[
                // Column headers are legends: this is the position the mono
                // tracked-out caps were designed for, and it is what makes a
                // table read as a labelled panel rather than a spreadsheet.
                'nf-legend px-5 py-3 border-b border-border align-bottom',
                alignClass(col.align),
                col.hideOnSm ? 'hidden md:table-cell' : '',
              ]"
              scope="col"
            >
              {{ col.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-if="loading && rows.length === 0">
            <tr
              v-for="i in skeletonRows"
              :key="`sk-${i}`"
              class="border-b border-border last:border-0"
              :aria-busy="true"
            >
              <td
                v-for="col in columns"
                :key="col.key"
                :class="[
                  'px-5 py-4 align-middle',
                  alignClass(col.align),
                  col.cellClass ?? '',
                  col.hideOnSm ? 'hidden md:table-cell' : '',
                ]"
              >
                <Skeleton
                  :width="col.align === 'right' ? '3rem' : '70%'"
                  height="0.75rem"
                  rounded="sm"
                />
              </td>
            </tr>
          </template>
          <tr v-else-if="rows.length === 0">
            <td :colspan="columns.length">
              <EmptyState
                :icon="Inbox"
                :title="emptyTitle ?? t('common.empty.title')"
                :description="emptyDescription ?? t('common.empty.description')"
              >
                <template v-if="$slots['empty-action']" #action>
                  <slot name="empty-action" />
                </template>
              </EmptyState>
            </td>
          </tr>
          <tr
            v-for="row in rows"
            v-else
            :key="row.id"
            :data-row-id="row.id"
            :class="[
              'border-b border-border last:border-0 transition-colors duration-150 ease-soft',
              clickable
                ? 'group/row hover:bg-surface-hover cursor-pointer focus-within:bg-surface-hover'
                : '',
              rowClass?.(row) ?? '',
            ]"
            @click="clickable && $emit('row-click', row)"
          >
            <td
              v-for="col in columns"
              :key="col.key"
              :class="[
                'px-5 py-3.5 text-fg align-middle',
                alignClass(col.align),
                col.cellClass ?? '',
                col.hideOnSm ? 'hidden md:table-cell' : '',
              ]"
            >
              <slot :name="`cell-${String(col.key)}`" :row="row" :value="cellValue(row, col.key)">
                {{ cellValue(row, col.key) ?? '—' }}
              </slot>
            </td>
          </tr>
        </tbody>
      </table>
      <!-- Loading overlay shown when refetching with rows already on screen -->
      <div
        v-if="loading && rows.length > 0"
        class="absolute inset-x-0 top-0 h-0.5 bg-primary-500/40 overflow-hidden"
      >
        <div class="h-full w-1/3 bg-primary-500 animate-pulse" />
      </div>
    </div>

    <!-- Mobile: stacked cards. Tables don't survive narrow viewports cleanly,
         so we flip to a vertical key/value layout that stays touch-friendly. -->
    <div class="md:hidden relative">
      <template v-if="loading && rows.length === 0">
        <div
          v-for="i in skeletonRows"
          :key="`sk-card-${i}`"
          class="border-b border-border last:border-0 p-3 space-y-2"
          :aria-busy="true"
        >
          <Skeleton width="50%" height="1rem" rounded="sm" />
          <Skeleton width="80%" height="0.75rem" rounded="sm" />
          <Skeleton width="60%" height="0.75rem" rounded="sm" />
        </div>
      </template>
      <div v-else-if="rows.length === 0">
        <EmptyState
          :icon="Inbox"
          :title="emptyTitle ?? t('common.empty.title')"
          :description="emptyDescription ?? t('common.empty.description')"
        >
          <template v-if="$slots['empty-action']" #action>
            <slot name="empty-action" />
          </template>
        </EmptyState>
      </div>
      <ul v-else class="divide-y divide-border">
        <li
          v-for="row in rows"
          :key="row.id"
          :data-row-id="row.id"
          :class="[
            'px-4 py-4 flex flex-col gap-2.5',
            clickable ? 'active:bg-surface-hover cursor-pointer' : '',
            rowClass?.(row) ?? '',
          ]"
          @click="clickable && $emit('row-click', row)"
        >
          <!-- Title row: primary column + chevron / actions on the right -->
          <div class="flex items-start justify-between gap-3">
            <div v-if="primaryCol" class="min-w-0 flex-1 text-[15px] font-semibold text-fg">
              <slot
                :name="`cell-${String(primaryCol.key)}`"
                :row="row"
                :value="cellValue(row, primaryCol.key)"
              >
                {{ cellValue(row, primaryCol.key) ?? '—' }}
              </slot>
            </div>
            <div v-if="actionsCol" class="flex-shrink-0" @click.stop>
              <slot
                :name="`cell-${String(actionsCol.key)}`"
                :row="row"
                :value="cellValue(row, actionsCol.key)"
              />
            </div>
            <ChevronRight
              v-else-if="clickable"
              class="w-4 h-4 text-fg-muted flex-shrink-0 mt-1"
              aria-hidden="true"
            />
          </div>

          <!-- Label/value rows for every other column -->
          <dl
            v-if="detailCols.length"
            class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]"
          >
            <template v-for="col in detailCols" :key="col.key">
              <dt class="text-fg-muted whitespace-nowrap">{{ col.label }}</dt>
              <dd class="text-fg min-w-0 break-words text-right">
                <slot :name="`cell-${String(col.key)}`" :row="row" :value="cellValue(row, col.key)">
                  {{ cellValue(row, col.key) ?? '—' }}
                </slot>
              </dd>
            </template>
          </dl>
        </li>
      </ul>
      <!-- Loading bar mirror -->
      <div
        v-if="loading && rows.length > 0"
        class="absolute inset-x-0 top-0 h-0.5 bg-primary-500/40 overflow-hidden"
      >
        <div class="h-full w-1/3 bg-primary-500 animate-pulse" />
      </div>
    </div>

    <slot name="footer" />
  </div>
</template>
