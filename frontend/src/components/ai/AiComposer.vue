<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Send } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'

/** The one place on the page that takes input. */
defineProps<{
  pending: boolean
  /** Provider is off — the composer is read-only until it comes back. */
  disabled: boolean
}>()

const emit = defineEmits<{ (e: 'submit'): void }>()

const question = defineModel<string>({ required: true })
const liteContext = defineModel<boolean>('liteContext', { required: true })

const { t } = useI18n()

function onEnter(ev: KeyboardEvent) {
  // Enter sends; Shift+Enter inserts a newline (textarea default).
  if (ev.key === 'Enter' && !ev.shiftKey) {
    ev.preventDefault()
    emit('submit')
  }
}
</script>

<template>
  <form class="nf-card p-3 space-y-2.5" @submit.prevent="emit('submit')">
    <textarea
      v-model="question"
      rows="3"
      class="nf-input resize-none"
      :placeholder="t('ai.askView.placeholder')"
      :disabled="disabled || pending"
      :aria-label="t('ai.askView.placeholder')"
      @keydown="onEnter"
    />
    <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <label
        class="flex items-center gap-2 text-xs text-fg-muted cursor-pointer select-none"
        :title="t('ai.askView.liteContextHint')"
      >
        <input
          v-model="liteContext"
          type="checkbox"
          class="rounded border-border-strong accent-primary-600"
          :disabled="pending"
        />
        <span>{{ t('ai.askView.liteContextLabel') }}</span>
      </label>
      <div class="flex items-center gap-3 ml-auto">
        <span class="text-xs text-fg-subtle hidden sm:inline">
          {{ t('ai.askView.composerHint') }}
        </span>
        <Button
          type="submit"
          variant="primary"
          :loading="pending"
          :disabled="!question.trim() || disabled"
        >
          <Send class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.askView.send') }}
        </Button>
      </div>
    </div>
  </form>
</template>
