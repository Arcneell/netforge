<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Whether to render the wordmark next to the glyph. */
    showWordmark?: boolean
    size?: number
  }>(),
  { showWordmark: true, size: 28 },
)
// Mirrors assets/logo.svg + public/favicon.svg — one identity across the site,
// the browser tab and the app. Three nodes on a diagonal: the smallest honest
// picture of what NetForge holds.
</script>

<template>
  <span class="inline-flex items-center gap-2.5 select-none">
    <svg
      :width="size"
      :height="size"
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <rect width="64" height="64" rx="14" fill="#4F46E5" />
      <path
        d="M 21 43 L 32 32 L 43 21"
        stroke="#FFFFFF"
        stroke-opacity="0.55"
        stroke-width="3.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      <circle cx="21" cy="43" r="5" fill="#FFFFFF" fill-opacity="0.55" />
      <circle cx="32" cy="32" r="5" fill="#FFFFFF" fill-opacity="0.8" />
      <circle cx="43" cy="21" r="5.5" fill="#FFFFFF" />
    </svg>
    <span v-if="showWordmark" class="text-md font-semibold text-fg tracking-[-0.02em]">
      NetForge
    </span>
  </span>
</template>
