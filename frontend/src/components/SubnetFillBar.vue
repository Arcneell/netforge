<script setup lang="ts">
import { computed } from 'vue'

/**
 * Compact fill-rate bar for subnets. Same green / amber / red ramp as
 * the dashboard, used in both the list view and the tree view so the
 * triage signal stays consistent across the IPAM screens.
 *
 * The whole component degrades gracefully when `usable` is 0 (e.g. a
 * /32 with no recorded IP): the bar just shows an empty track.
 */
const props = withDefaults(
  defineProps<{
    used: number
    usable: number
    /** Compact = bar only (used in dense tables). Full = bar + "n / N · x%". */
    variant?: 'compact' | 'full'
    /** Bar width override — Tailwind class. Defaults to a comfortable 4rem. */
    barClass?: string
  }>(),
  { variant: 'compact', barClass: 'w-16' },
)

const ratio = computed(() => {
  if (!props.usable) return 0
  return Math.min(1, props.used / props.usable)
})

const percent = computed(() => Math.round(ratio.value * 100))

const fillClass = computed(() => {
  if (ratio.value >= 0.8) return 'bg-danger'
  if (ratio.value >= 0.5) return 'bg-warning'
  return 'bg-success'
})
</script>

<template>
  <span class="inline-flex items-center gap-1.5 tabular-nums" :title="`${used} / ${usable}`">
    <span :class="['h-1.5 bg-muted rounded-full overflow-hidden flex-shrink-0', barClass]">
      <span
        :class="['block h-full transition-all', fillClass]"
        :style="{ width: `${ratio * 100}%` }"
        :aria-valuenow="percent"
        aria-valuemin="0"
        aria-valuemax="100"
        role="progressbar"
      />
    </span>
    <span v-if="variant === 'full'" class="text-xs text-fg-muted">
      {{ used }}
      <span class="opacity-60">/ {{ usable }}</span>
      <span class="ml-1 font-medium text-fg">{{ percent }}%</span>
    </span>
    <span v-else class="text-[11px] text-fg-muted w-9 text-right">{{ percent }}%</span>
  </span>
</template>
