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
  neutral: 'bg-muted text-fg-muted border-border',
  primary:
    'bg-primary-50 text-primary-700 border-primary-200 dark:bg-primary-100/20 dark:text-primary-50 dark:border-primary-100/30',
  success: 'bg-success/10 text-success border-success/30',
  warning: 'bg-warning/10 text-warning border-warning/30',
  danger: 'bg-danger/10 text-danger border-danger/30',
  muted: 'bg-transparent text-fg-muted border-border',
}

const sizeClass = {
  sm: 'px-1.5 h-5 text-[11px]',
  md: 'px-2 h-6 text-xs',
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
  'inline-flex items-center gap-1 rounded border font-medium align-middle whitespace-nowrap',
  sizeClass[props.size],
  props.color ? '' : tonePresets[props.tone],
  props.monospace ? 'font-mono tabular-nums' : '',
])
</script>

<template>
  <span :class="classes" :style="inlineStyle">
    <slot />
  </span>
</template>
