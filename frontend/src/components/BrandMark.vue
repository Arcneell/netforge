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
// Monochrome duotone (cyan-700 ground, cyan-400 endpoint dot), confident
// "N" letterform, no skeuomorphic ornament.
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
      <rect width="64" height="64" rx="14" fill="#0e7490" />
      <path
        d="M 19 47 L 19 17 L 45 47 L 45 17"
        stroke="#ffffff"
        stroke-width="5.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <circle cx="45" cy="17" r="3.6" fill="#22d3ee" />
    </svg>
    <span v-if="showWordmark" class="font-semibold text-fg tracking-tight">NetForge</span>
  </span>
</template>
