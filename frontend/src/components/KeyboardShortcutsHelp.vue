<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import Modal from '@/components/ui/Modal.vue'
import { SHORTCUTS } from '@/composables/useShortcuts'

defineProps<{ open: boolean }>()
defineEmits<{ (e: 'close'): void }>()
const { t } = useI18n()
</script>

<template>
  <Modal :open="open" :title="t('shortcuts.title')" size="md" @close="$emit('close')">
    <p class="text-xs text-fg-muted mb-3">{{ t('shortcuts.subtitle') }}</p>
    <ul class="space-y-1.5">
      <li
        v-for="s in SHORTCUTS"
        :key="s.display"
        class="flex items-center justify-between py-1 px-2 rounded hover:bg-surface-hover gap-3"
      >
        <span class="text-sm text-fg">{{ t(s.descriptionKey) }}</span>
        <span class="flex items-center gap-1 flex-shrink-0">
          <template v-for="(part, i) in s.display.split(' ')" :key="i">
            <span v-if="part === '/'" class="text-xs text-fg-muted">/</span>
            <kbd
              v-else
              class="font-mono text-xs px-1.5 py-0.5 rounded bg-muted border border-border text-fg whitespace-nowrap"
            >
              {{ part }}
            </kbd>
          </template>
        </span>
      </li>
    </ul>
  </Modal>
</template>
