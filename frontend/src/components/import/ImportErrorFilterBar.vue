<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { AlertTriangle } from '@lucide/vue'
import { formatNumber } from '@/utils/formatters'

/**
 * Error triage bar. One filter drives every error table underneath it — a
 * 400-row failure is unusable as a flat dump. The search box only appears
 * once there are enough rows for scanning to be the slower option.
 */
defineProps<{
  count: number
}>()

const query = defineModel<string>('query', { required: true })

const { t } = useI18n()
</script>

<template>
  <div class="bg-danger/5 px-4 sm:px-5 py-3 flex flex-wrap items-center justify-between gap-3">
    <div class="min-w-0">
      <p class="inline-flex items-center gap-2 text-base font-medium text-danger">
        <AlertTriangle class="w-4 h-4 flex-shrink-0" aria-hidden="true" />
        {{ t('import.report.errorsTitle') }} ({{ formatNumber(count) }})
      </p>
      <p class="text-xs text-fg-muted mt-0.5">{{ t('import.report.errorsHint') }}</p>
    </div>
    <input
      v-if="count > 10"
      v-model="query"
      type="search"
      class="nf-input nf-input-control w-full sm:w-64"
      :placeholder="t('import.report.errorsFilter')"
      :aria-label="t('import.report.errorsFilter')"
    />
  </div>
</template>
