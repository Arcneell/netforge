<script setup lang="ts">
import { computed } from 'vue'

type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger' | 'muted'

const props = withDefaults(
  defineProps<{
    tone?: Tone
    /** Override with any hex color — used for VLAN-specific palettes. */
    color?: string | null
    monospace?: boolean
    size?: 'sm' | 'md'
  }>(),
  { tone: 'neutral', size: 'sm', color: null, monospace: false },
)

const tonePresets: Record<Tone, string> = {
  // Neutrals: zinc-100 fill, fg-muted text — reads as "metadata", recedes.
  neutral: 'bg-muted text-fg dark:text-fg-muted border-border',
  // Primary tone is intentionally subtle in dark mode (indigo-400/20 vs the
  // saturated indigo-600 a button would use). Badges shouldn't compete with
  // CTAs even when they share the accent hue.
  primary:
    'bg-primary-50 text-primary-700 border-primary-200/80 dark:bg-primary-400/10 dark:text-primary-300 dark:border-primary-400/30',
  success: 'bg-success/10 text-success border-success/30 dark:bg-success/15 dark:border-success/40',
  warning: 'bg-warning/10 text-warning border-warning/30 dark:bg-warning/15 dark:border-warning/40',
  danger: 'bg-danger/10 text-danger border-danger/30 dark:bg-danger/15 dark:border-danger/40',
  // Muted is bare-bones, used as a "ghost" badge to align with table rows.
  muted: 'bg-transparent text-fg-muted border-border/80',
}

const sizeClass = {
  // Pixel-perfect heights to line up with table rows and form controls.
  sm: 'px-1.5 h-5 text-[11px] leading-none',
  md: 'px-2 h-6 text-xs leading-none',
}

// Custom color wins. Border is the same hex with reduced opacity; we apply both
// inline so it works in light and dark without authoring a Tailwind class.
const inlineStyle = computed(() => {
  if (!props.color) return undefined
  return {
    backgroundColor: `${props.color}1A`, // ~10% alpha
    color: props.color,
    borderColor: `${props.color}55`,
  }
})

const classes = computed(() => [
  // iOS pill — fully rounded, no harsh border in most cases. Borders only
  // surface in dark mode where the tinted fills need a thin edge to read.
  'inline-flex items-center gap-1 rounded-full border font-medium align-middle whitespace-nowrap',
  sizeClass[props.size],
  props.color ? '' : tonePresets[props.tone],
  props.monospace ? 'font-mono tabular-nums tracking-tight' : '',
])
</script>

<template>
  <span :class="classes" :style="inlineStyle">
    <slot />
  </span>
</template>
