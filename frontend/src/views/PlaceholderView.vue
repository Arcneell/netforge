<script setup lang="ts">
import { Construction } from 'lucide-vue-next'

defineProps<{
  titleKey: string
}>()
</script>

<template>
  <div class="p-4 sm:p-6 max-w-7xl mx-auto">
    <header class="mb-6">
      <h1 class="text-2xl font-semibold tracking-tight">{{ $t(titleKey) }}</h1>
    </header>
    <div class="nf-card p-10 flex flex-col items-center text-center gap-3">
      <Construction class="w-10 h-10 text-fg-muted" aria-hidden="true" />
      <p class="text-sm text-fg-muted">{{ $t('common.comingSoon') }}</p>
    </div>
  </div>
</template>
