<script setup lang="ts" generic="T extends { id: number | string }">
import { useI18n } from 'vue-i18n'
import { Inbox } from 'lucide-vue-next'
import EmptyState from '@/components/EmptyState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'

/**
 * Minimal accessible table with explicit column slots and one row-click event.
 * No client-side sorting, filtering, or virtualization on purpose — those
 * concerns belong to the parent page so it can push them down to the API.
 */
export interface DataTableColumn {
  key: string
  label: string
  /** Tailwind classes applied to <th> and each <td>. */
  cellClass?: string
  /** Right-align numeric columns. */
  align?: 'left' | 'right' | 'center'
  /** Hide on narrow screens. */
  hideOnSm?: boolean
}

withDefaults(
  defineProps<{
    columns: DataTableColumn[]
    rows: T[]
    loading?: boolean
    /** Title shown in the empty-state when there are zero rows. */
    emptyTitle?: string
    emptyDescription?: string
    /** Adds a hover style + cursor on rows when truthy. */
    clickable?: boolean
    /** Skeleton rows rendered during the first load (no rows yet). */
    skeletonRows?: number
  }>(),
  { loading: false, clickable: false, skeletonRows: 6 },
)

defineEmits<{
  (e: 'row-click', row: T): void
}>()

const { t } = useI18n()

function alignClass(a: DataTableColumn['align']): string {
  if (a === 'right') return 'text-right'
  if (a === 'center') return 'text-center'
  return 'text-left'
}
</script>

<template>
  <div class="nf-card overflow-hidden">
    <div class="relative overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="bg-muted/60 border-b border-border">
            <th
              v-for="col in columns"
              :key="col.key"
              :class="[
                'px-4 py-2 text-xs font-medium text-fg-muted uppercase tracking-wide',
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
                  'px-4 py-3 align-middle',
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
            :class="[
              'border-b border-border last:border-0',
              clickable
                ? 'hover:bg-surface-hover cursor-pointer focus-within:bg-surface-hover'
                : '',
            ]"
            @click="clickable && $emit('row-click', row)"
          >
            <td
              v-for="col in columns"
              :key="col.key"
              :class="[
                'px-4 py-2 text-fg align-middle',
                alignClass(col.align),
                col.cellClass ?? '',
                col.hideOnSm ? 'hidden md:table-cell' : '',
              ]"
            >
              <slot :name="`cell-${col.key}`" :row="row" :value="(row as any)[col.key]">
                {{ (row as any)[col.key] ?? '—' }}
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
    <slot name="footer" />
  </div>
</template>
