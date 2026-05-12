<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Whether to render the wordmark next to the glyph. */
    showWordmark?: boolean
    size?: number
  }>(),
  { showWordmark: true, size: 28 },
)
// Mark mirrors assets/logo.svg + public/favicon.svg — single visual
// identity across the site, the browser tab, and the README banner.
// Mini-topology: 3 nodes on a diagonal, luminance grading dim→bright,
// literal echo of what the Topology view draws.
</script>

<template>
  <span class="inline-flex items-center gap-2 select-none">
    <svg
      :width="size"
      :height="size"
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect width="64" height="64" rx="14" fill="#083344" />
      <path
        d="M 20 44 L 32 32 L 44 20"
        stroke="#0891b2"
        stroke-width="4"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <circle cx="20" cy="44" r="5.5" fill="#0e7490" />
      <circle cx="32" cy="32" r="5.5" fill="#22d3ee" />
      <circle cx="44" cy="20" r="6" fill="#ffffff" />
    </svg>
    <span v-if="showWordmark" class="font-semibold text-fg tracking-tight">NetForge</span>
  </span>
</template>
