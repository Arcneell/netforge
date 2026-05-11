<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Whether to render the wordmark next to the glyph. */
    showWordmark?: boolean
    size?: number
  }>(),
  { showWordmark: true, size: 28 },
)
</script>

<template>
  <span class="inline-flex items-center gap-2 select-none">
    <svg
      :width="size"
      :height="size"
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect width="32" height="32" rx="8" fill="url(#nf-grad)" />
      <path
        d="M9 22V10l8 8V10m-2 12h6"
        stroke="white"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <defs>
        <linearGradient id="nf-grad" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
          <stop stop-color="#06B6D4" />
          <stop offset="1" stop-color="#0E7490" />
        </linearGradient>
      </defs>
    </svg>
    <span v-if="showWordmark" class="font-semibold text-fg tracking-tight">NetForge</span>
  </span>
</template>
