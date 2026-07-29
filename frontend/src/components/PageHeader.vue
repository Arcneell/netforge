<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    subtitle?: string
    /** Optional legend above the title — scope, count, or the family the page
     *  belongs to. Information only; leave it off rather than decorate. */
    legend?: string
  }>(),
  { subtitle: undefined, legend: undefined },
)
</script>

<template>
  <!-- Title, one line of context, and the page's actions. No rule underneath:
       the space below does the separating.

       The title is the display face at its expanded width — the single place on
       an ordinary page where the type has a personality of its own. Everything
       else here stays quiet so it can. -->
  <header class="flex items-start justify-between gap-6 mb-7 flex-wrap">
    <div class="min-w-0">
      <p v-if="legend" class="nf-legend mb-1.5">{{ legend }}</p>
      <h1 class="nf-display text-2xl sm:text-3xl font-bold text-fg">{{ title }}</h1>
      <p
        v-if="subtitle || $slots.help"
        class="text-base text-fg-muted mt-2 max-w-2xl inline-flex items-center gap-1.5"
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
