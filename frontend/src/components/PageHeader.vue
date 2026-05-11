<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <header class="flex items-start justify-between gap-4 mb-6 flex-wrap">
    <div class="min-w-0">
      <h1 class="text-2xl font-semibold tracking-tight text-fg">{{ title }}</h1>
      <p v-if="subtitle" class="text-sm text-fg-muted mt-1">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="flex items-center gap-2 flex-shrink-0">
      <slot name="actions" />
    </div>
  </header>
</template>
