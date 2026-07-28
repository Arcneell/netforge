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

// Soft tinted labels, no borders. A badge qualifies a value; it should never
// out-shout the value itself.
const tonePresets: Record<Tone, string> = {
  neutral: 'bg-muted text-fg-muted',
  primary: 'bg-primary-50 text-primary-700 dark:bg-primary-500/15 dark:text-primary-300',
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/10 text-warning',
  danger: 'bg-danger/10 text-danger',
  muted: 'bg-transparent text-fg-subtle',
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
    color: props.color,
  }
})

const classes = computed(() => [
  'inline-flex items-center gap-1 rounded font-medium align-middle whitespace-nowrap leading-none',
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
