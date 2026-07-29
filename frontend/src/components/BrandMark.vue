<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Whether to render the wordmark next to the glyph. */
    showWordmark?: boolean
    size?: number
    /** Render for a dark plate ground (the sidebar rail) rather than a page. */
    onPlate?: boolean
  }>(),
  { showWordmark: true, size: 28, onPlate: false },
)
// Geometry is kept identical across public/favicon.svg, assets/logo.svg and
// assets/logo-banner.svg — one identity across the app, the browser tab and the
// README. Change one, change all four.
//
// The mark is a /24 rendered as sixteen cells with seven allocated: the app's
// own subject, at the smallest size it still reads. It is the same picture the
// dashboard's address band and the subnet detail grid draw, three scales apart,
// so the logo is a statement of what the product is rather than an abstraction
// laid on top of it. The chamfered top-right corner is the milled edge of a
// rack panel, and the one place in the interface that shape is allowed.
//
// The stair silhouette of the filled cells is deliberate: address space fills
// row-major from the bottom of the range, so a partly-allocated block always
// looks like this.
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
      <!-- The plate, with its chamfer. -->
      <path d="M0 0 H50 L64 14 V64 H0 Z" fill="#141716" />

      <!-- Unallocated cells: present, but empty. -->
      <g fill="#E9ECE6" fill-opacity="0.12">
        <rect x="33" y="23" width="8" height="8" />
        <rect x="43" y="23" width="8" height="8" />
        <rect x="23" y="33" width="8" height="8" />
        <rect x="33" y="33" width="8" height="8" />
        <rect x="43" y="33" width="8" height="8" />
        <rect x="13" y="43" width="8" height="8" />
        <rect x="23" y="43" width="8" height="8" />
        <rect x="33" y="43" width="8" height="8" />
        <rect x="43" y="43" width="8" height="8" />
      </g>

      <!-- Allocated cells: teal, filling row-major from the top of the block. -->
      <g fill="#2FADA6">
        <rect x="13" y="13" width="8" height="8" />
        <rect x="23" y="13" width="8" height="8" />
        <rect x="33" y="13" width="8" height="8" />
        <rect x="43" y="13" width="8" height="8" />
        <rect x="13" y="23" width="8" height="8" />
        <rect x="23" y="23" width="8" height="8" />
        <rect x="13" y="33" width="8" height="8" />
      </g>
    </svg>
    <span
      v-if="showWordmark"
      class="nf-display text-md font-bold uppercase"
      :class="onPlate ? 'text-plate-fg' : 'text-fg'"
      style="letter-spacing: 0.02em"
    >
      NetForge
    </span>
  </span>
</template>
