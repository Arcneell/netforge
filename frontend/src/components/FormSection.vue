<script setup lang="ts">
import { computed } from 'vue'

/**
 * One titled panel inside a `<FormPage>`. Groups related fields under a
 * heading and a line explaining what they control, so a long form reads as a
 * handful of decisions instead of a wall of inputs.
 *
 * The body flows into up to three columns on a wide screen — the page has the
 * full 1400px to work with, and a "VLAN id" box has no business being 700px
 * wide. A field that needs the whole row opts in with
 * `class="sm:col-span-2 lg:col-span-3"`; a description or a textarea usually
 * does. Set `columns` to 1 or 2 for panels holding wide controls.
 */
const props = withDefaults(
  defineProps<{
    title: string
    description?: string
    columns?: 1 | 2 | 3
  }>(),
  { description: undefined, columns: 3 },
)

const gridClass = computed(
  () =>
    ({
      1: 'grid-cols-1',
      2: 'grid-cols-1 sm:grid-cols-2',
      3: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
    })[props.columns],
)
</script>

<template>
  <section class="nf-card overflow-hidden">
    <header class="px-6 py-4 border-b border-border bg-bg/40">
      <div class="flex items-center gap-2">
        <h2 class="nf-section-title">{{ title }}</h2>
        <slot name="header-aside" />
      </div>
      <p v-if="description" class="text-sm text-fg-muted mt-1 max-w-3xl">{{ description }}</p>
    </header>
    <div :class="['p-6 grid gap-x-6 gap-y-5', gridClass]">
      <slot />
    </div>
  </section>
</template>
