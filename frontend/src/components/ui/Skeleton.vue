<script setup lang="ts">
withDefaults(
  defineProps<{
    width?: string
    height?: string
    rounded?: 'sm' | 'md' | 'lg' | 'full'
  }>(),
  { width: '100%', height: '0.75rem', rounded: 'sm' },
)
</script>

<template>
  <span
    class="nf-skeleton inline-block align-middle"
    :class="{
      'rounded-sm': rounded === 'sm',
      'rounded-md': rounded === 'md',
      'rounded-lg': rounded === 'lg',
      'rounded-full': rounded === 'full',
    }"
    :style="{ width, height }"
    aria-hidden="true"
  />
</template>
