<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  page: number
  pageSize: number
  total: number
}>()

const emit = defineEmits<{
  (e: 'update:page', v: number): void
}>()

const { t } = useI18n()

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const start = computed(() => (props.total === 0 ? 0 : (props.page - 1) * props.pageSize + 1))
const end = computed(() => Math.min(props.page * props.pageSize, props.total))
const canPrev = computed(() => props.page > 1)
const canNext = computed(() => props.page < totalPages.value)

function go(p: number) {
  const clamped = Math.min(Math.max(1, p), totalPages.value)
  if (clamped !== props.page) emit('update:page', clamped)
}
</script>

<template>
  <div
    class="flex items-center justify-between gap-4 px-5 py-3 border-t border-border text-sm text-fg-muted"
  >
    <span aria-live="polite" class="tabular-nums">
      {{ t('common.pagination.range', { start, end, total }) }}
    </span>
    <div class="flex items-center gap-1">
      <button
        type="button"
        class="inline-flex items-center justify-center w-8 h-8 rounded-md text-fg-muted hover:bg-surface-hover hover:text-fg disabled:opacity-35 disabled:pointer-events-none transition-colors duration-150 ease-soft"
        :disabled="!canPrev"
        :aria-label="t('common.pagination.previous')"
        @click="go(page - 1)"
      >
        <ChevronLeft class="w-4 h-4" aria-hidden="true" />
      </button>
      <span class="px-2 tabular-nums">
        {{ t('common.pagination.pageOf', { page, total: totalPages }) }}
      </span>
      <button
        type="button"
        class="inline-flex items-center justify-center w-8 h-8 rounded-md text-fg-muted hover:bg-surface-hover hover:text-fg disabled:opacity-35 disabled:pointer-events-none transition-colors duration-150 ease-soft"
        :disabled="!canNext"
        :aria-label="t('common.pagination.next')"
        @click="go(page + 1)"
      >
        <ChevronRight class="w-4 h-4" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>
