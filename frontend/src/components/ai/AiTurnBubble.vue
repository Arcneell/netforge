<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Bot, User as UserIcon } from 'lucide-vue-next'
import AiEntityChips from '@/components/ai/AiEntityChips.vue'
import AiMessageBody from '@/components/ai/AiMessageBody.vue'
import type { AiTurn } from '@/composables/useAiChat'

/** One exchange line: avatar, who spoke, the rendered body, its sources. */
defineProps<{
  turn: AiTurn
}>()

const { t } = useI18n()
</script>

<template>
  <article class="flex gap-3 px-4 py-4 sm:px-5 sm:py-5">
    <span
      v-if="turn.role === 'assistant'"
      class="flex-shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-md bg-primary-600 text-white"
      aria-hidden="true"
    >
      <Bot class="w-4 h-4" />
    </span>
    <span
      v-else
      class="flex-shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-md bg-muted text-fg-muted border border-border"
      aria-hidden="true"
    >
      <UserIcon class="w-4 h-4" />
    </span>

    <div class="min-w-0 flex-1">
      <div class="flex items-baseline gap-2 mb-1.5">
        <span class="text-sm font-semibold text-fg">
          {{ turn.role === 'assistant' ? t('ai.askView.assistant') : t('ai.askView.you') }}
        </span>
        <span v-if="turn.latency_ms !== undefined" class="text-xs text-fg-subtle tabular-nums">
          {{ t('ai.askView.latency', { ms: turn.latency_ms }) }}
        </span>
      </div>

      <AiMessageBody :text="turn.text" :role="turn.role" />

      <AiEntityChips v-if="turn.entities && turn.entities.length" :entities="turn.entities" />
    </div>
  </article>
</template>
