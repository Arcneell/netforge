<script setup lang="ts">
import { Loader2 } from '@lucide/vue'

withDefaults(
  defineProps<{
    size?: 'sm' | 'md' | 'lg'
    label?: string
  }>(),
  { size: 'md', label: undefined },
)

const sizeClass = {
  sm: 'w-4 h-4',
  md: 'w-6 h-6',
  lg: 'w-10 h-10',
}
</script>

<template>
  <span class="inline-flex items-center gap-2 text-fg-muted" role="status" :aria-label="label">
    <Loader2 :class="[sizeClass[size], 'animate-spin']" aria-hidden="true" />
    <span v-if="label" class="text-sm">{{ label }}</span>
  </span>
</template>
