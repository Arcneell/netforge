<script setup lang="ts">
import { computed } from 'vue'
import { formatNumber } from '@/utils/formatters'

/**
 * One number of the compact report readout — four figures on a line, not
 * four hero cards.
 */
const props = withDefaults(
  defineProps<{
    value: number
    label: string
    /** `error` paints the figure red only when it is actually non-zero. */
    tone?: 'neutral' | 'success' | 'error'
  }>(),
  { tone: 'neutral' },
)

const valueClass = computed(() => {
  if (props.tone === 'success') return 'text-success'
  if (props.tone === 'error') return props.value > 0 ? 'text-danger' : 'text-fg-subtle'
  return 'text-fg'
})
</script>

<template>
  <p class="flex items-baseline gap-1.5">
    <span class="text-lg font-semibold font-mono tabular-nums" :class="valueClass">
      {{ formatNumber(value) }}
    </span>
    <span class="text-xs text-fg-muted">{{ label }}</span>
  </p>
</template>
