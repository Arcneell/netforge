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

// Stamped labels: a tint, a hairline in the same hue, square corners. The
// hairline is what turns a soft SaaS chip into something that reads as printed
// onto the surface — and it survives on the cabinet-grey ground, where a
// borderless 10%-tint chip goes muddy. A badge still qualifies a value; it
// should never out-shout the value itself.
const tonePresets: Record<Tone, string> = {
  neutral: 'bg-muted text-fg-muted border-border-strong',
  primary:
    'bg-primary-50 text-primary-800 border-primary-300 ' +
    'dark:bg-primary-500/15 dark:text-primary-200 dark:border-primary-700',
  success: 'bg-success/10 text-success border-success/35',
  warning: 'bg-warning/10 text-warning border-warning/35',
  danger: 'bg-danger/10 text-danger border-danger/35',
  muted: 'bg-transparent text-fg-subtle border-transparent',
}

const sizeClass = {
  sm: 'px-1.5 h-5 text-2xs',
  md: 'px-2 h-6 text-xs',
}

// Custom colour wins — applied inline so it works in both themes without
// authoring a Tailwind class per VLAN.
const inlineStyle = computed(() => {
  if (!props.color) return undefined
  return {
    backgroundColor: `${props.color}1F`, // ~12% alpha
    borderColor: `${props.color}59`, // ~35% alpha — matches the tone presets
    color: props.color,
  }
})

const classes = computed(() => [
  'inline-flex items-center gap-1 rounded border font-medium align-middle whitespace-nowrap leading-none',
  sizeClass[props.size],
  props.color ? '' : tonePresets[props.tone],
  props.monospace ? 'font-mono' : '',
])
</script>

<template>
  <span :class="classes" :style="inlineStyle">
    <slot />
  </span>
</template>
