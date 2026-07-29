<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check } from 'lucide-vue-next'

/**
 * Progress rail — where you are in the job.
 *
 * The import is a four-beat sequence — pick, dry-run, review, apply — and it
 * runs identically in both modes, so the caller derives the operator's
 * position from whichever panel is on screen and the rail never contradicts
 * the panel underneath it.
 */
const props = defineProps<{
  /** 1-based beat the operator is on. */
  currentStep: number
  /** A report came back applied: every beat reads as done. */
  applied: boolean
}>()

const { t } = useI18n()

const steps = computed(() => [
  { n: 1, title: t('import.steps.selectTitle'), hint: t('import.steps.selectHint') },
  { n: 2, title: t('import.steps.validateTitle'), hint: t('import.steps.validateHint') },
  { n: 3, title: t('import.steps.reviewTitle'), hint: t('import.steps.reviewHint') },
  { n: 4, title: t('import.steps.applyTitle'), hint: t('import.steps.applyHint') },
])

type StepState = 'done' | 'current' | 'todo'

function stepState(n: number): StepState {
  if (props.applied) return 'done'
  if (n < props.currentStep) return 'done'
  if (n === props.currentStep) return 'current'
  return 'todo'
}

function stepBadgeClass(state: StepState): string {
  if (state === 'done') return 'bg-success/10 text-success'
  if (state === 'current')
    return 'bg-primary-500/15 text-primary-700 dark:text-primary-300 ring-1 ring-inset ring-primary-500/40'
  return 'bg-muted text-fg-subtle'
}

function stepStateLabel(state: StepState): string {
  if (state === 'done') return t('import.steps.done')
  if (state === 'current') return t('import.steps.current')
  return t('import.steps.todo')
}
</script>

<template>
  <ol
    class="nf-card p-4 sm:p-5 mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 lg:gap-0"
    :aria-label="t('import.steps.aria')"
  >
    <li
      v-for="(s, i) in steps"
      :key="s.n"
      class="flex items-start gap-3 min-w-0"
      :class="i > 0 ? 'lg:border-l lg:border-border lg:pl-5' : 'lg:pr-5'"
      :aria-current="stepState(s.n) === 'current' ? 'step' : undefined"
    >
      <span
        class="inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-semibold tabular-nums flex-shrink-0 mt-0.5 transition-colors duration-150 ease-soft"
        :class="stepBadgeClass(stepState(s.n))"
      >
        <Check v-if="stepState(s.n) === 'done'" class="w-3.5 h-3.5" aria-hidden="true" />
        <template v-else>{{ s.n }}</template>
      </span>
      <div class="min-w-0">
        <p
          class="text-base font-medium"
          :class="stepState(s.n) === 'todo' ? 'text-fg-muted' : 'text-fg'"
        >
          {{ s.title }}
          <span class="sr-only">— {{ stepStateLabel(stepState(s.n)) }}</span>
        </p>
        <p class="text-xs text-fg-muted mt-0.5">{{ s.hint }}</p>
      </div>
    </li>
  </ol>
</template>
