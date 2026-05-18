<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <header class="flex items-start justify-between gap-4 mb-8 flex-wrap">
    <div class="min-w-0">
      <!-- iOS-style oversized title with tight tracking. The bigger size gives
           pages a clear visual anchor and matches what feels right next to the
           generous card radii in the rest of the UI. -->
      <h1 class="text-3xl sm:text-[2rem] font-semibold tracking-[-0.025em] text-fg leading-[1.15]">
        {{ title }}
      </h1>
      <p v-if="subtitle" class="text-[15px] text-fg-muted mt-2 max-w-2xl leading-relaxed">
        {{ subtitle }}
      </p>
    </div>
    <div v-if="$slots.actions" class="flex items-center gap-2 flex-shrink-0">
      <slot name="actions" />
    </div>
  </header>
</template>
