<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Whether to render the wordmark next to the glyph. */
    showWordmark?: boolean
    size?: number
  }>(),
  { showWordmark: true, size: 28 },
)
// SVG geometry mirrors assets/logo.svg (used in the README banner and the
// repo favicon), so the site, the docs, and the browser tab show the exact
// same mark — hexagon shell + 4-node network graph, cyan gradient.
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
      <defs>
        <linearGradient id="nf-hex" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#22d3ee" />
          <stop offset="55%" stop-color="#0891b2" />
          <stop offset="100%" stop-color="#0c4a6e" />
        </linearGradient>
        <linearGradient id="nf-shine" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#ffffff" stop-opacity="0.28" />
          <stop offset="60%" stop-color="#ffffff" stop-opacity="0" />
        </linearGradient>
      </defs>
      <path
        d="M 32 3 L 57 17.5 L 57 46.5 L 32 61 L 7 46.5 L 7 17.5 Z"
        fill="url(#nf-hex)"
        stroke="#0c4a6e"
        stroke-width="1.5"
        stroke-linejoin="round"
      />
      <path d="M 32 3 L 57 17.5 L 57 32 L 7 32 L 7 17.5 Z" fill="url(#nf-shine)" />
      <g stroke="#ecfeff" stroke-width="3" stroke-linecap="round" fill="none">
        <line x1="22" y1="22" x2="22" y2="44" />
        <line x1="22" y1="44" x2="42" y2="22" />
        <line x1="42" y1="22" x2="42" y2="44" />
      </g>
      <g fill="#ecfeff" stroke="#0e7490" stroke-width="1">
        <circle cx="22" cy="22" r="3.6" />
        <circle cx="22" cy="44" r="3.6" />
        <circle cx="42" cy="22" r="3.6" />
        <circle cx="42" cy="44" r="3.6" />
      </g>
    </svg>
    <span v-if="showWordmark" class="font-semibold text-fg tracking-tight">NetForge</span>
  </span>
</template>
