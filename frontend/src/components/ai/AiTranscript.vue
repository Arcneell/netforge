<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowRight, Bot, Sparkles } from '@lucide/vue'
import EmptyState from '@/components/EmptyState.vue'
import AiTurnBubble from '@/components/ai/AiTurnBubble.vue'
import type { AiTurn } from '@/composables/useAiChat'

/**
 * The conversation itself. Its own scroll region so a long answer stays
 * pinned to the bottom without dragging the composer off screen — the parent
 * drives that through the exposed `scrollToBottom()`.
 */
defineProps<{
  turns: AiTurn[]
  pending: boolean
}>()

const emit = defineEmits<{ (e: 'use-suggestion', text: string): void }>()

const { t } = useI18n()
const scrollerRef = ref<HTMLDivElement | null>(null)

const suggestions = [
  'ai.askView.example1',
  'ai.askView.example2',
  'ai.askView.example3',
  'ai.askView.example4',
]

async function scrollToBottom() {
  await nextTick()
  const el = scrollerRef.value
  if (el) el.scrollTop = el.scrollHeight
}

defineExpose({ scrollToBottom })
</script>

<template>
  <div ref="scrollerRef" class="nf-card overflow-y-auto min-h-[18rem] max-h-[min(60vh,42rem)] mb-3">
    <!-- Empty: explain + one-click examples -->
    <EmptyState
      v-if="turns.length === 0"
      :icon="Sparkles"
      :title="t('ai.askView.emptyTitle')"
      :description="t('ai.askView.emptyDescription')"
    >
      <template #action>
        <div class="grid sm:grid-cols-2 gap-2 max-w-xl text-left">
          <button
            v-for="key in suggestions"
            :key="key"
            type="button"
            class="group nf-card nf-interactive flex items-start gap-2 px-3 py-2.5 text-left"
            @click="emit('use-suggestion', t(key))"
          >
            <span class="text-base text-fg leading-snug flex-1">{{ t(key) }}</span>
            <ArrowRight
              class="w-3.5 h-3.5 text-fg-subtle flex-shrink-0 mt-0.5 opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-200 ease-soft"
              aria-hidden="true"
            />
          </button>
        </div>
      </template>
    </EmptyState>

    <!-- Thread. One hairline per turn boundary — the cheapest way to say
         "this is where the answer starts". -->
    <div v-else class="divide-y divide-border">
      <AiTurnBubble v-for="turn in turns" :key="turn.id" :turn="turn" />

      <!-- Thinking indicator. Opacity-only CSS animation, removed the
           instant the first token lands (`pending` flips on delta #1). -->
      <div v-if="pending" class="flex gap-3 px-4 py-4 sm:px-5 sm:py-5" aria-busy="true">
        <span
          class="flex-shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-md bg-primary-600 text-white"
          aria-hidden="true"
        >
          <Bot class="w-4 h-4" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-sm font-semibold text-fg mb-1.5">{{ t('ai.askView.assistant') }}</p>
          <p class="inline-flex items-center gap-2 text-base text-fg-muted">
            <span class="inline-flex gap-1" aria-hidden="true">
              <span class="w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse" />
              <span
                class="w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse"
                style="animation-delay: 160ms"
              />
              <span
                class="w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse"
                style="animation-delay: 320ms"
              />
            </span>
            {{ t('ai.askView.thinking') }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
