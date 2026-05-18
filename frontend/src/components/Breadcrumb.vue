<script setup lang="ts">
import { ChevronRight } from 'lucide-vue-next'
import type { RouteLocationRaw } from 'vue-router'

export interface BreadcrumbItem {
  /** Display text. Falls back to the literal string if i18n isn't involved. */
  label: string
  /** Where this crumb points. Omit on the final item — it renders as the
   *  current page title and is no longer a link. */
  to?: RouteLocationRaw
}

defineProps<{
  items: BreadcrumbItem[]
}>()
</script>

<template>
  <!--
    Breadcrumb pattern: one row of small text just above the PageHeader. Each
    parent is a router-link; the last crumb is the current page (non-link).

    Why a dedicated component rather than ad-hoc layout per view: every detail
    page (Subnet, Switch, future Device/IP) needs the same "where am I?" cue
    and the same back-link behavior. Centralising it keeps the styling, the
    separator icon, and the truncation rules identical across the app.
  -->
  <nav aria-label="Breadcrumb" class="flex items-center gap-1 text-xs text-fg-muted mb-3 min-w-0">
    <ol class="flex items-center gap-1 min-w-0">
      <li v-for="(item, i) in items" :key="i" class="flex items-center gap-1 min-w-0">
        <RouterLink
          v-if="item.to && i < items.length - 1"
          :to="item.to"
          class="hover:text-fg transition-colors truncate max-w-[18ch]"
        >
          {{ item.label }}
        </RouterLink>
        <span
          v-else
          class="text-fg font-medium truncate max-w-[28ch]"
          :aria-current="i === items.length - 1 ? 'page' : undefined"
        >
          {{ item.label }}
        </span>
        <ChevronRight
          v-if="i < items.length - 1"
          class="w-3.5 h-3.5 text-fg-muted/60 flex-shrink-0"
          aria-hidden="true"
        />
      </li>
    </ol>
  </nav>
</template>
