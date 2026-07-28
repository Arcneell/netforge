<script setup lang="ts">
import { computed } from 'vue'

/**
 * The fill-rate bar. One implementation, reused everywhere a capacity ratio
 * is shown — subnet list, subnet tree, dashboard buckets, and the identity
 * block of the detail pages — so the triage signal reads identically across
 * the app.
 *
 * Ramp: green while there's room, amber past half, red once the block is
 * effectively spent (0.5 / 0.8 thresholds, unchanged).
 *
 * The whole component degrades gracefully when `usable` is 0 (e.g. a
 * /32 with no recorded IP): the bar just shows an empty track.
 */
const props = withDefaults(
  defineProps<{
    used: number
    usable: number
    /**
     * `compact` = bar + percentage (dense tables).
     * `full`    = bar + "x% n / N" on one line.
     * `block`   = figures on top, full-width bar underneath — for the
     *             definition cell of a detail page.
     */
    variant?: 'compact' | 'full' | 'block'
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

// The whole track carries the progressbar semantics — the fill is a purely
// visual child. Screen readers get the ratio plus the raw counts.
const barWidth = computed(() => ({ width: `${ratio.value * 100}%` }))
</script>

<template>
  <!-- Block: the figures lead, the bar restates them. Used where the bar has
       a full column to itself rather than sharing a table cell. -->
  <div v-if="variant === 'block'" class="w-full">
    <div class="flex items-baseline justify-between gap-3">
      <span class="text-base font-medium text-fg tabular-nums">{{ percent }}%</span>
      <span class="text-xs text-fg-muted tabular-nums">{{ used }} / {{ usable }}</span>
    </div>
    <span
      class="mt-2 block h-1.5 rounded-full bg-border overflow-hidden"
      role="progressbar"
      :aria-valuenow="percent"
      :aria-valuetext="`${used} / ${usable}`"
      aria-valuemin="0"
      aria-valuemax="100"
    >
      <span
        :class="['block h-full rounded-full transition-[width] duration-200 ease-soft', fillClass]"
        :style="barWidth"
      />
    </span>
  </div>

  <span v-else class="inline-flex items-center gap-2.5" :title="`${used} / ${usable}`">
    <span
      :class="['h-1.5 rounded-full bg-border overflow-hidden flex-shrink-0', barClass]"
      role="progressbar"
      :aria-valuenow="percent"
      :aria-valuetext="`${used} / ${usable}`"
      aria-valuemin="0"
      aria-valuemax="100"
    >
      <span
        :class="['block h-full rounded-full transition-[width] duration-200 ease-soft', fillClass]"
        :style="barWidth"
      />
    </span>
    <span v-if="variant === 'full'" class="text-xs text-fg-muted whitespace-nowrap tabular-nums">
      <span class="font-medium text-fg">{{ percent }}%</span>
      <span class="ml-1.5">{{ used }} / {{ usable }}</span>
    </span>
    <span v-else class="text-xs text-fg-muted w-9 text-right tabular-nums">{{ percent }}%</span>
  </span>
</template>
