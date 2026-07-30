<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, History, Plus } from '@lucide/vue'
import PageHeader from '@/components/PageHeader.vue'
import Button from '@/components/ui/Button.vue'
import HelpTooltip from '@/components/ui/HelpTooltip.vue'
import AiComposer from '@/components/ai/AiComposer.vue'
import AiHistoryDrawer from '@/components/ai/AiHistoryDrawer.vue'
import AiTranscript from '@/components/ai/AiTranscript.vue'
import { useAiChat } from '@/composables/useAiChat'

const { t } = useI18n()

const historyOpen = ref(false)
const transcriptRef = ref<InstanceType<typeof AiTranscript> | null>(null)

async function scrollToBottom() {
  await transcriptRef.value?.scrollToBottom()
}

const {
  status,
  turns,
  input,
  pending,
  liteContext,
  activeConversationId,
  conversations,
  conversationsLoading,
  conversationsError,
  hasConversation,
  composerDisabled,
  send,
  newChat,
  loadConversations,
  openConversation,
  removeConversation,
} = useAiChat({ scrollToBottom })

/**
 * Drawer-picked conversation: load it then close the drawer so the
 * user can read the transcript without an overlay in the way.
 */
async function onPickConversation(id: number): Promise<void> {
  await openConversation(id)
  historyOpen.value = false
}
</script>

<template>
  <div class="px-4 py-8 sm:px-8 max-w-[1400px] mx-auto nf-stagger">
    <PageHeader :title="t('ai.askView.title')" :subtitle="t('ai.askView.subtitle')">
      <template #help>
        <HelpTooltip :text="t('ai.askView.help')" placement="bottom" />
      </template>
      <template #actions>
        <Button
          variant="ghost"
          size="sm"
          :aria-label="t('ai.askView.historyTitle')"
          @click="historyOpen = true"
        >
          <History class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.askView.historyTitle') }}
          <span
            v-if="conversations.length > 0"
            class="ml-1 px-1.5 py-0.5 rounded bg-muted text-2xs tabular-nums leading-none"
          >
            {{ conversations.length }}
          </span>
        </Button>
        <Button
          v-if="hasConversation"
          variant="secondary"
          size="sm"
          :disabled="pending"
          @click="newChat"
        >
          <Plus class="w-4 h-4" aria-hidden="true" />
          {{ t('ai.askView.newChat') }}
        </Button>
      </template>
    </PageHeader>

    <!-- The conversation column. Narrower than the page so answer text keeps
         a comfortable measure; the prose itself is capped at 70ch below. -->
    <section class="mx-auto w-full max-w-4xl">
      <!-- Provider off: say so once, at the top, with the fix. -->
      <div
        v-if="status && !status.enabled"
        class="nf-card border-l-[3px] border-l-warning p-4 mb-4 flex items-start gap-3"
      >
        <AlertTriangle
          class="w-4 h-4 text-warning flex-shrink-0 mt-0.5"
          :stroke-width="1.9"
          aria-hidden="true"
        />
        <div class="min-w-0">
          <p class="text-base font-medium text-fg">{{ t('ai.askView.disabledTitle') }}</p>
          <p class="text-sm text-fg-muted mt-0.5">{{ t('ai.askView.disabledHint') }}</p>
        </div>
      </div>

      <AiTranscript
        ref="transcriptRef"
        :turns="turns"
        :pending="pending"
        @use-suggestion="(text) => (input = text)"
      />

      <AiComposer
        v-model="input"
        v-model:lite-context="liteContext"
        :pending="pending"
        :disabled="composerDisabled"
        @submit="send"
      />
    </section>

    <AiHistoryDrawer
      :open="historyOpen"
      :conversations="conversations"
      :loading="conversationsLoading"
      :error="conversationsError"
      :active-id="activeConversationId"
      @close="historyOpen = false"
      @refresh="loadConversations"
      @pick="onPickConversation"
      @remove="removeConversation"
    />
  </div>
</template>
