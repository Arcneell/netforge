<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Share2, ArrowRight } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import Badge from '@/components/ui/Badge.vue'

/**
 * The topology graph is being reworked. Rather than ship the old canvas
 * behind a new interface, the route says plainly that the view is paused and
 * points at the two pages that answer most of what people came here for.
 * `TopologyView.vue` is left untouched on disk and will be reinstated.
 */
const { t } = useI18n()

const alternatives = [
  { to: '/switches', labelKey: 'nav.switches', descKey: 'topology.wip.viaSwitches' },
  { to: '/devices', labelKey: 'nav.devices', descKey: 'topology.wip.viaDevices' },
]
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="t('nav.topology')" :subtitle="t('topology.subtitle')">
      <template #actions>
        <Badge tone="warning" size="md">{{ t('common.wip') }}</Badge>
      </template>
    </PageHeader>

    <div class="nf-card px-6 py-12 sm:px-12 text-center max-w-2xl mx-auto">
      <Share2 class="w-6 h-6 text-fg-subtle mx-auto" :stroke-width="1.75" aria-hidden="true" />
      <p class="text-lg font-semibold text-fg mt-4">{{ t('topology.wip.title') }}</p>
      <p class="text-base text-fg-muted mt-2 max-w-md mx-auto">{{ t('topology.wip.body') }}</p>

      <div class="grid sm:grid-cols-2 gap-3 mt-8 text-left">
        <RouterLink
          v-for="alt in alternatives"
          :key="alt.to"
          :to="alt.to"
          class="group nf-card nf-interactive p-4"
        >
          <span class="flex items-center gap-2 text-base font-medium text-fg">
            {{ t(alt.labelKey) }}
            <ArrowRight
              class="w-3.5 h-3.5 text-fg-subtle opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200 ease-soft"
              aria-hidden="true"
            />
          </span>
          <span class="block text-sm text-fg-muted mt-1">{{ t(alt.descKey) }}</span>
        </RouterLink>
      </div>
    </div>
  </div>
</template>
