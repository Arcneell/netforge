<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    subtitle?: string
  }>(),
  { subtitle: undefined },
)
</script>

<template>
  <!-- Title, one line of context, and the page's actions. No rule underneath:
       the space below does the separating. -->
  <header class="flex items-start justify-between gap-6 mb-8 flex-wrap">
    <div class="min-w-0">
      <h1 class="text-2xl font-semibold text-fg tracking-[-0.02em]">{{ title }}</h1>
      <p
        v-if="subtitle || $slots.help"
        class="text-base text-fg-muted mt-1.5 max-w-2xl inline-flex items-center gap-1.5"
      >
        <span>{{ subtitle }}</span>
        <slot name="help" />
      </p>
    </div>
    <div v-if="$slots.actions" class="flex items-center gap-2 flex-shrink-0">
      <slot name="actions" />
    </div>
  </header>
</template>
