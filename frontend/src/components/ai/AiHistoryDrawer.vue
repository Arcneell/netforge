<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { History, Trash2 } from '@lucide/vue'
import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { Conversation } from '@/api'

/**
 * History drawer: shows the persisted conversation list on demand
 * (PageHeader "Historique" button). Re-uses the project Modal so it inherits
 * scroll-lock + focus-trap + topmost-stack handling.
 */
defineProps<{
  open: boolean
  conversations: Conversation[]
  loading: boolean
  error: string | null
  activeId: number | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'refresh'): void
  (e: 'pick', id: number): void
  (e: 'remove', id: number): void
}>()

const { t } = useI18n()

function onRemove(id: number, ev: Event) {
  ev.stopPropagation()
  emit('remove', id)
}
</script>

<template>
  <Modal :open="open" :title="t('ai.askView.historyTitle')" size="md" @close="emit('close')">
    <p v-if="loading" class="text-base text-fg-muted">
      {{ t('common.loading') }}
    </p>
    <div v-else-if="error" class="space-y-3">
      <p class="text-base text-danger break-words">{{ error }}</p>
      <p class="text-sm text-fg-muted">{{ t('ai.askView.historyErrorHint') }}</p>
      <Button variant="secondary" size="sm" @click="emit('refresh')">
        {{ t('common.refresh') }}
      </Button>
    </div>
    <EmptyState
      v-else-if="conversations.length === 0"
      :icon="History"
      :title="t('ai.askView.historyEmpty')"
      :description="t('ai.askView.historyEmptyHint')"
      size="sm"
    />
    <ul v-else class="-mx-2 max-h-[60vh] overflow-y-auto space-y-1">
      <li
        v-for="c in conversations"
        :key="c.id"
        :class="[
          'group flex items-start gap-1 rounded-md pr-1',
          c.id === activeId ? 'bg-primary-50 dark:bg-primary-500/15' : 'hover:bg-surface-hover',
          'transition-colors duration-150 ease-soft',
        ]"
      >
        <button
          type="button"
          :class="[
            'flex-1 min-w-0 text-left px-3 py-2 rounded-md text-base leading-snug',
            c.id === activeId ? 'text-primary-700 dark:text-primary-300 font-medium' : 'text-fg',
          ]"
          :aria-current="c.id === activeId ? 'true' : undefined"
          @click="emit('pick', c.id)"
        >
          <span class="line-clamp-2 break-words block">
            {{ c.title || c.preview || t('ai.askView.untitledConversation') }}
          </span>
          <span v-if="c.turn_count" class="nf-label block mt-0.5">
            {{ c.turn_count }} {{ t('ai.askView.turnsLabel') }}
          </span>
        </button>
        <button
          type="button"
          class="flex-shrink-0 mt-1.5 inline-flex items-center justify-center w-7 h-7 rounded-md text-fg-subtle opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:text-danger hover:bg-surface-hover transition-colors duration-150 ease-soft"
          :aria-label="t('common.delete')"
          @click="onRemove(c.id, $event)"
        >
          <Trash2 class="w-3.5 h-3.5" aria-hidden="true" />
        </button>
      </li>
    </ul>
  </Modal>
</template>
