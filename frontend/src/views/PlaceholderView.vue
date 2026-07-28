<script setup lang="ts">
import { Construction } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'

defineProps<{
  titleKey: string
}>()
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="$t(titleKey)" />
    <div class="nf-card px-6 py-14 flex flex-col items-center text-center">
      <Construction class="w-6 h-6 text-fg-subtle" :stroke-width="1.75" aria-hidden="true" />
      <p class="text-md font-medium text-fg mt-3">{{ $t('common.comingSoon') }}</p>
    </div>
  </div>
</template>
