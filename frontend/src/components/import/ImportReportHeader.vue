<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, ArrowRight, CheckCircle2, Info } from '@lucide/vue'
import Badge from '@/components/ui/Badge.vue'

/**
 * Shared head of both import reports: tone icon, title, one-line summary,
 * applied badge, the stats row (caller-supplied) and the sentence telling the
 * operator what to do next.
 */
const props = defineProps<{
  title: string
  summary: string
  /** Rendered before the summary as "prefix · summary" (single mode names the
   *  entity that was imported). */
  summaryPrefix?: string
  applied: boolean
  errorCount: number
}>()

const { t } = useI18n()

const tone = computed<'success' | 'warning' | 'danger'>(() => {
  if (props.applied) return 'success'
  if (props.errorCount > 0) return 'danger'
  return 'warning'
})

// Sentence telling the operator what to do next, derived from the report that
// is actually on screen.
const nextStepMessage = computed(() => {
  if (props.applied) return t('import.report.nextStepDone')
  if (props.errorCount > 0) return t('import.report.nextStepFix')
  return t('import.report.nextStepApply')
})
</script>

<template>
  <header class="p-4 sm:p-5 border-b border-border">
    <div class="flex items-start gap-3 flex-wrap">
      <CheckCircle2
        v-if="tone === 'success'"
        class="w-5 h-5 text-success flex-shrink-0 mt-0.5"
        aria-hidden="true"
      />
      <AlertTriangle
        v-else-if="tone === 'danger'"
        class="w-5 h-5 text-danger flex-shrink-0 mt-0.5"
        aria-hidden="true"
      />
      <Info v-else class="w-5 h-5 text-warning flex-shrink-0 mt-0.5" aria-hidden="true" />
      <div class="min-w-0 flex-1">
        <h2 class="nf-section-title">{{ title }}</h2>
        <p class="text-sm text-fg-muted mt-0.5">
          <span v-if="summaryPrefix">{{ summaryPrefix }} ·</span>
          {{ summary }}
        </p>
      </div>
      <Badge :tone="applied ? 'success' : 'muted'" size="md">
        {{ applied ? t('import.report.appliedTrue') : t('import.report.appliedFalse') }}
      </Badge>
    </div>

    <!-- Compact readout — the numbers on one line, not one hero card each. -->
    <div class="mt-4 flex flex-wrap items-baseline gap-x-6 gap-y-2">
      <slot name="stats" />
    </div>

    <p
      v-if="nextStepMessage"
      class="mt-4 flex items-start gap-2 rounded-md bg-muted px-3 py-2 text-sm text-fg"
    >
      <ArrowRight class="w-4 h-4 text-fg-subtle flex-shrink-0 mt-0.5" aria-hidden="true" />
      <span>{{ nextStepMessage }}</span>
    </p>
  </header>
</template>
