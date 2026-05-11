<script setup lang="ts">
import { Network, Tags, Router as RouterIcon, Server } from 'lucide-vue-next'
import { useAuth } from '@/composables/useAuth'

const { user } = useAuth()

const cards = [
  { key: 'nav.subnets', icon: Network, to: '/subnets' },
  { key: 'nav.vlans', icon: Tags, to: '/vlans' },
  { key: 'nav.switches', icon: RouterIcon, to: '/switches' },
  { key: 'nav.devices', icon: Server, to: '/devices' },
]
</script>

<template>
  <div class="p-6 max-w-7xl mx-auto">
    <header class="mb-6">
      <h1 class="text-2xl font-semibold tracking-tight">{{ $t('nav.dashboard') }}</h1>
      <p class="text-sm text-fg-muted mt-1">
        {{ $t('app.tagline') }}
        <span v-if="user?.display_name" class="ml-1">— {{ user.display_name }}.</span>
      </p>
    </header>

    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <RouterLink
        v-for="c in cards"
        :key="c.key"
        :to="c.to"
        class="nf-card p-5 hover:border-primary-300 hover:bg-surface-hover transition group"
      >
        <div class="flex items-center gap-3">
          <span
            class="inline-flex items-center justify-center w-10 h-10 rounded-md bg-primary-50 text-primary-600 dark:bg-primary-100/20 dark:text-primary-50"
          >
            <component :is="c.icon" class="w-5 h-5" aria-hidden="true" />
          </span>
          <div>
            <p class="text-sm font-medium text-fg">{{ $t(c.key) }}</p>
            <p class="text-xs text-fg-muted">{{ $t('common.comingSoon') }}</p>
          </div>
        </div>
      </RouterLink>
    </section>
  </div>
</template>
