<script setup lang="ts">
import { RouterLink } from 'vue-router'

/**
 * Sub-navigation for a workspace — a group of related pages that used to be
 * separate sidebar entries. Sits directly under the app topbar and stays put
 * while the page below it scrolls, so the group you're in is always visible.
 */
export interface WorkspaceTab {
  to: string
  label: string
}

defineProps<{ tabs: WorkspaceTab[] }>()
</script>

<template>
  <div class="sticky top-0 z-10 bg-bg/85 backdrop-blur-sm border-b border-border">
    <nav
      class="flex items-center gap-6 px-4 sm:px-8 max-w-[1400px] mx-auto overflow-x-auto"
      aria-label="Sections"
    >
      <RouterLink
        v-for="tab in tabs"
        :key="tab.to"
        v-slot="{ href, navigate, isActive }"
        :to="tab.to"
        custom
      >
        <a
          :href="href"
          :class="['nf-tab', isActive ? 'nf-tab-active' : '']"
          :aria-current="isActive ? 'page' : undefined"
          @click="navigate"
        >
          {{ tab.label }}
        </a>
      </RouterLink>
    </nav>
  </div>
</template>
