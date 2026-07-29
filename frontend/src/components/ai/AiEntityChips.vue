<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Network, Server, Tags, Router as RouterIcon } from 'lucide-vue-next'
import type { QueryEntityRef } from '@/api'

/** The "sources" chip row under an answer: every record the model leaned on,
 *  linked to its page when the SPA has one. */
defineProps<{
  entities: QueryEntityRef[]
}>()

const { t } = useI18n()

const entityIcon: Record<string, typeof Server> = {
  switch: RouterIcon,
  port: RouterIcon,
  device: Server,
  vlan: Tags,
  subnet: Network,
}

function entityRoute(e: QueryEntityRef): string | null {
  switch (e.type) {
    case 'switch':
      return `/switches/${e.id}`
    case 'subnet':
      return `/subnets/${e.id}`
    case 'vlan':
      return '/vlans'
    case 'device':
      return '/devices'
    default:
      return null
  }
}

function entityLabel(e: QueryEntityRef): string {
  return e.name || `${e.type} #${e.id}`
}
</script>

<template>
  <div class="mt-3 max-w-[70ch]">
    <p class="nf-label mb-1.5">{{ t('ai.askView.sourcesTitle') }}</p>
    <div class="flex flex-wrap gap-1.5">
      <RouterLink
        v-for="(e, idx) in entities"
        :key="`${e.type}-${e.id}-${idx}`"
        v-slot="{ href, navigate }"
        :to="entityRoute(e) ?? ''"
        custom
      >
        <a
          :href="entityRoute(e) ? href : undefined"
          :class="[
            'inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border text-xs font-medium',
            'transition-colors duration-150 ease-soft',
            entityRoute(e)
              ? 'border-border bg-surface text-fg hover:border-primary-500 hover:text-primary-600 dark:hover:text-primary-400 cursor-pointer'
              : 'border-transparent bg-muted text-fg-subtle cursor-default',
          ]"
          @click="entityRoute(e) ? navigate($event) : null"
        >
          <component
            :is="entityIcon[e.type] ?? Server"
            class="w-3 h-3 flex-shrink-0"
            aria-hidden="true"
          />
          {{ entityLabel(e) }}
        </a>
      </RouterLink>
    </div>
  </div>
</template>
