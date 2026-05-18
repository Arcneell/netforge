<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <header class="flex items-start justify-between gap-4 mb-6 flex-wrap">
    <div class="min-w-0">
      <!-- text-[1.625rem] = 26px : sits between Tailwind's xl (24) and 2xl (30),
           tighter than 2xl with -0.02em tracking. Reads as a proper page title
           without dwarfing the dense tables that usually follow. -->
      <h1 class="text-[1.625rem] font-semibold tracking-[-0.02em] text-fg leading-tight">
        {{ title }}
      </h1>
      <p v-if="subtitle" class="text-sm text-fg-muted mt-1.5 max-w-2xl">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="flex items-center gap-2 flex-shrink-0">
      <slot name="actions" />
    </div>
  </header>
</template>
